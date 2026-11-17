"""A failed code qualification must restore its feature flag and policy."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest


async def _exercise(monkeypatch, phase, was_enabled=False):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "native"))
    lane = importlib.import_module("code_checks")
    original = {"version": 1, "rule_effect": "allow", "rules": []}
    state = {"enabled": was_enabled, "policy": original.copy()}
    policy_writes = []
    feature_writes = []

    def respond(request):
        import json

        body = json.loads(request.content) if request.content else None
        if request.url.path.endswith("/features"):
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "flags": {
                            "enable_tool_security_policies": {"value": was_enabled}
                        }
                    },
                )
            value = body["flags"]["enable_tool_security_policies"]
            feature_writes.append(value)
            state["enabled"] = value
            return httpx.Response(
                503 if phase == "feature-enable" and len(feature_writes) == 1 else 200,
                json={},
            )
        assert request.url.path.endswith("/policy/config")
        if request.method == "GET":
            return httpx.Response(
                503 if phase == "policy-read" else 200, json=state["policy"]
            )
        policy_writes.append(body)
        if phase == "policy-restore" and len(policy_writes) == 2:
            return httpx.Response(503, json={})
        state["policy"] = {**body, "version": len(policy_writes) + 1}
        if len(policy_writes) == 1:
            if phase == "policy-reply-loss":
                raise httpx.ReadError("Policy reply lost", request=request)
            if phase == "policy-save":
                return httpx.Response(503, json={})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        checks = SimpleNamespace(
            client=client,
            control=AsyncMock(
                return_value={"state": "off"},
                side_effect=RuntimeError("Probe failed") if phase == "probe" else None,
            ),
            call=AsyncMock(
                return_value={
                    "data": {
                        "operations": [{"status": "pending"}],
                        "result": {"success": False},
                    }
                },
                side_effect=AssertionError("Body failed") if phase == "body" else None,
            ),
            passed=Mock(),
        )
        caught = None
        try:
            await lane._approval_gate(checks, "http://fixture", "script")
        except (AssertionError, RuntimeError, httpx.HTTPError) as error:
            caught = error
    return state, original, policy_writes, feature_writes, checks, caught


@pytest.mark.parametrize(
    "phase",
    [
        "feature-enable",
        "policy-read",
        "probe",
        "policy-save",
        "policy-reply-loss",
        "body",
    ],
)
async def test_setup_or_body_failure_restores_original_flag_and_any_changed_policy(
    monkeypatch, phase
):
    state, original, writes, flags, checks, caught = await _exercise(monkeypatch, phase)
    assert caught is not None
    assert state["enabled"] is False
    assert {k: v for k, v in state["policy"].items() if k != "version"} == {
        k: v for k, v in original.items() if k != "version"
    }
    assert flags[-1] is False
    assert len(writes) == (
        2 if phase in {"policy-save", "policy-reply-loss", "body"} else 0
    )
    checks.passed.assert_not_called()


async def test_policy_restore_failure_cannot_prevent_feature_flag_restore(monkeypatch):
    state, _, _, flags, checks, caught = await _exercise(monkeypatch, "policy-restore")
    assert isinstance(caught, AssertionError)
    assert state["enabled"] is False and flags[-1] is False
    checks.passed.assert_not_called()


@pytest.mark.parametrize("was_enabled", [False, True])
async def test_successful_qualification_restores_the_preexisting_flag_and_policy(
    monkeypatch, was_enabled
):
    state, original, _, flags, checks, caught = await _exercise(
        monkeypatch, "success", was_enabled
    )
    assert caught is None
    assert state["enabled"] is was_enabled and flags[-1] is was_enabled
    assert state["policy"]["rule_effect"] == original["rule_effect"]
    assert state["policy"]["rules"] == original["rules"]
    checks.passed.assert_called_once()


@pytest.mark.parametrize("failure", ["status", "reply-loss"])
async def test_raw_tool_setup_failure_restores_tool_exposure(monkeypatch, failure):
    import json

    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "native"))
    lane = importlib.import_module("code_checks")
    original = {"states": {"ha_list_services": "enabled"}, "llm_api_overrides": {}}
    state = {"states": original["states"].copy()}
    writes = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json=original)
        body = json.loads(request.content)
        writes.append(body)
        state["states"] = body["states"]
        if len(writes) == 1:
            if failure == "reply-loss":
                raise httpx.ReadError("Tool settings reply lost", request=request)
            return httpx.Response(503, json={})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        checks = SimpleNamespace(
            client=client,
            path="/fixture",
            rpc=AsyncMock(
                return_value={"result": {"isError": True, "error": "READ_ONLY"}}
            ),
            call=AsyncMock(),
            passed=Mock(),
        )
        with pytest.raises(httpx.HTTPError):
            await lane._raw_boundaries(checks, "http://fixture")
    assert state["states"] == original["states"]
    assert writes[-1] == {
        "states": original["states"],
        "llm_api": original["llm_api_overrides"],
    }
    assert checks.path == "/fixture"
    checks.call.assert_not_awaited()
    checks.passed.assert_not_called()
