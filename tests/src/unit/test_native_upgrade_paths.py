"""Reject misleading green upgrades and exercise persisted HTTP credentials."""

from __future__ import annotations

import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.native.upgrade_paths import exercise
from tests.native.upgrade_paths.auth import enroll, refresh
from tests.native.upgrade_paths.client import Client
from tests.native.upgrade_paths.contracts import (
    PHASES,
    PROFILES,
    PROTOCOLS,
    UpgradeFailure,
    catalogue_differences,
    fingerprint,
    report_passed,
    validate_phase,
)


def _phase():
    return {
        "passed": True,
        "connection_hash": "a" * 64,
        "identity": "b" * 64,
        "grant_origin": "main",
        "connected": True,
        "witness_preserved": True,
        "oauth": True,
        "old_grant_refreshed": True,
        "protocols": dict.fromkeys(PROTOCOLS, True),
        "catalogue_changes": [],
    }


def _report():
    return {
        "cleanup_complete": True,
        "sources_verified": True,
        "profiles": [
            {"profile": profile.name, "phases": {phase: _phase() for phase in PHASES}}
            for profile in PROFILES
        ],
    }


def test_upgrade_and_native_are_independent_gates():
    report = _report()
    assert report_passed(report, False) and report_passed(report, True)
    report["profiles"][0]["phases"]["native"] = {
        "passed": False,
        "failure": "ConnectError",
    }
    assert report_passed(report, False)
    assert not report_passed(report, True)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.update(cleanup_complete=False),
        lambda report: report.update(sources_verified=False),
        lambda report: report.update(failure="TimeoutError"),
        lambda report: report["profiles"].pop(),
        lambda report: report["profiles"].append(report["profiles"][0]),
        lambda report: report["profiles"][0].update(cleanup_failed=True),
        lambda report: report["profiles"][0]["phases"].pop("upgraded"),
        lambda report: report["profiles"][0]["phases"]["upgraded"].update(
            passed="true"
        ),
        lambda report: report["profiles"][0]["phases"]["upgraded"].update(
            old_grant_refreshed=False
        ),
        lambda report: report["profiles"][0]["phases"]["upgraded"].update(
            grant_origin="candidate"
        ),
        lambda report: report["profiles"][0]["phases"]["upgraded"].update(
            identity="c" * 64
        ),
        lambda report: report["profiles"][0]["phases"]["upgraded"].update(
            connection_hash="c" * 64
        ),
        lambda report: report["profiles"][0]["phases"]["upgraded"].update(protocols={}),
        lambda report: report["profiles"][0]["phases"]["upgraded"].update(
            catalogue_changes=[{"kind": "tool_removed"}]
        ),
    ],
)
def test_missing_failed_or_reauthorized_evidence_cannot_pass(mutation):
    report = _report()
    mutation(report)
    assert not report_passed(report, False)
    assert not report_passed(report, True)


def test_absent_identity_cannot_validate_against_itself():
    with pytest.raises(UpgradeFailure):
        validate_phase({}, {"connected": True, "witness_preserved": True}, "")


def test_catalogue_allows_additions_but_preserves_existing_literal_contract():
    old = {
        "ha_test": {
            "inputSchema": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Old prose",
                        "enum": ["description"],
                    }
                },
                "required": ["description"],
            },
            "annotations": {"readOnlyHint": True},
        }
    }
    new = copy.deepcopy(old)
    new["ha_test"]["inputSchema"]["properties"]["optional"] = {"type": "integer"}
    new["ha_test"]["inputSchema"]["properties"]["description"]["description"] = (
        "New prose"
    )
    new["ha_new"] = {}
    assert catalogue_differences(old, new) == []
    new["ha_test"]["inputSchema"]["properties"]["description"]["enum"] = ["changed"]
    assert catalogue_differences(old, new) == [
        {"tool": "ha_test", "kind": "input_changed", "parameter": "description"}
    ]


@pytest.mark.parametrize(
    "change,kind",
    [
        (
            lambda tool: tool["inputSchema"].update(required=["extra"]),
            "required_input_added",
        ),
        (
            lambda tool: tool["annotations"].update(readOnlyHint=False),
            "annotation_changed",
        ),
        (
            lambda tool: tool["inputSchema"].update(additionalProperties=False),
            "schema_root_changed",
        ),
    ],
)
def test_catalogue_reports_breaking_changes(change, kind):
    before = {
        "ha_test": {
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True},
        }
    }
    after = copy.deepcopy(before)
    change(after["ha_test"])
    assert kind in {delta["kind"] for delta in catalogue_differences(before, after)}
    assert catalogue_differences(before, {}) == [
        {"tool": "ha_test", "kind": "tool_removed"}
    ]


def test_output_contract_changes_remain_visible():
    old = {
        "ha_test": {
            "inputSchema": {},
            "outputSchema": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            },
        }
    }
    changed = copy.deepcopy(old)
    changed["ha_test"]["outputSchema"]["properties"]["value"]["type"] = "string"
    assert catalogue_differences(old, changed) == [
        {"tool": "ha_test", "kind": "output_schema_changed"}
    ]


@pytest.mark.asyncio
async def test_refresh_reuses_old_endpoint_client_and_refresh_token():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"access_token": "renewed"})

    connection = {
        "oauth": {
            "client_id": "original-id",
            "client_secret": "original-secret",
            "token_endpoint": "http://127.0.0.1:8123/token",
        }
    }
    original = {"access_token": "old-access", "refresh_token": "main-refresh"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        renewed = await refresh(http, connection, original)
    assert str(seen[0].url) == connection["oauth"]["token_endpoint"]
    assert (
        seen[0].content
        == b"client_id=original-id&client_secret=original-secret&grant_type=refresh_token&refresh_token=main-refresh"
    )
    assert renewed == {"access_token": "renewed", "refresh_token": "main-refresh"}
    assert original["access_token"] == "old-access"


@pytest.mark.asyncio
async def test_ha_oauth_enrollment_uses_real_core_login_and_bound_code_exchange():
    from urllib.parse import urlencode

    seen = []
    challenge = None
    origin = "http://127.0.0.1:8123"
    oauth = origin + "/api/ha_mcp_tools/oauth"

    def handle(request):
        nonlocal challenge
        seen.append(request)
        path = request.url.path
        if path.endswith("/authorization-server"):
            return httpx.Response(
                200,
                json={
                    "registration_endpoint": oauth + "/register",
                    "authorization_endpoint": oauth + "/authorize",
                    "token_endpoint": oauth + "/token",
                },
            )
        if path.endswith("/register"):
            return httpx.Response(201, json={"client_id": "main-client"})
        if path.endswith("/authorize"):
            challenge = request.url.params["code_challenge"]
            return httpx.Response(
                302,
                headers={
                    "location": origin
                    + "/auth/authorize?"
                    + urlencode(
                        {
                            "client_id": "http://127.0.0.1:31999/",
                            "code_challenge": challenge,
                            "redirect_uri": "http://127.0.0.1:31999/upgrade-callback",
                        }
                    )
                },
            )
        if path == "/auth/login_flow":
            data = json.loads(request.content)
            assert data["handler"] == ["homeassistant", None]
            assert data["code_challenge"] == challenge
            return httpx.Response(200, json={"type": "form", "flow_id": "main-login"})
        if path == "/auth/login_flow/main-login":
            data = json.loads(request.content)
            assert (
                data["username"] == "run-admin" and data["password"] == "run-password"
            )
            return httpx.Response(
                200, json={"type": "create_entry", "result": "core-code"}
            )
        assert path == "/api/ha_mcp_tools/oauth/token"
        from urllib.parse import parse_qs

        data = parse_qs(request.content.decode())
        assert data["client_id"] == ["main-client"] and data["code"] == ["core-code"]
        assert data["grant_type"] == ["authorization_code"]
        return httpx.Response(
            200, json={"access_token": "main-access", "refresh_token": "main-refresh"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=False
    ) as http:
        identity, grant = await enroll(
            http,
            origin,
            "ha-oauth",
            {"username": "run-admin", "password": "run-password"},
            {},
        )
    assert identity == {"client_id": "main-client", "token_endpoint": oauth + "/token"}
    assert grant["refresh_token"] == "main-refresh"
    assert len(seen) == 6


@pytest.mark.asyncio
async def test_oauth_discovery_cannot_send_credentials_outside_the_instance():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "registration_endpoint": "http://127.0.0.1:9999/register",
                "authorization_endpoint": "http://127.0.0.1:8123/authorize",
                "token_endpoint": "http://127.0.0.1:8123/token",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(UpgradeFailure, match="oauth_endpoint_escaped_instance"):
            await enroll(http, "http://127.0.0.1:8123", "ha-oauth", {}, {})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_old_grant_refusal_never_falls_back_to_enrollment():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(400, json={"error": "invalid_grant"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(UpgradeFailure):
            await refresh(
                http,
                {
                    "oauth": {
                        "client_id": "main",
                        "token_endpoint": "http://127.0.0.1:8123/token",
                    }
                },
                {"refresh_token": "old"},
            )
    assert len(requests) == 1 and requests[0].url.path == "/token"


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "retained-token"])
async def test_http_client_preserves_actual_auth_method_and_session(token):
    seen = []

    def handle(request):
        seen.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"Mcp-Session-Id": "retained-session"},
            json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = Client(
            http,
            {"url": "http://127.0.0.1:8123/secret", "protocol": "2025-06-18"},
            token,
        )
        await client.rpc("tools/list")
        await client.rpc("tools/list")
    assert seen[0].headers.get("Authorization") == (
        "Bearer " + token if token else None
    )
    assert seen[1].headers["Mcp-Session-Id"] == "retained-session"
    assert all(request.url.path == "/secret" for request in seen)


@pytest.mark.asyncio
async def test_lost_write_response_is_not_replayed():
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadError("reply lost")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = Client(
            http, {"url": "http://127.0.0.1:8123/secret", "protocol": "2025-06-18"}, ""
        )
        with pytest.raises(UpgradeFailure, match="mcp_transport_failed") as error:
            await client.call("ha_call_service", {"service": "toggle"})
    assert len(calls) == 1
    assert error.value.diagnostic == {
        "operation": "tools/call",
        "protocol": "2025-06-18",
    }


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (403, b"secret-body", "mcp_http_refused"),
        (200, b"secret-body", "mcp_wire_invalid"),
    ],
)
async def test_rpc_diagnostics_locate_failure_without_exporting_endpoint_token_or_body(
    status, body, kind
):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, content=body))
    ) as http:
        client = Client(
            http,
            {"url": "http://127.0.0.1:8123/secret-path", "protocol": "2025-11-25"},
            "secret-token",
        )
        with pytest.raises(UpgradeFailure, match=kind) as error:
            await client.rpc("tools/list")
    diagnostic = error.value.diagnostic
    assert diagnostic["operation"] == "tools/list"
    assert diagnostic["protocol"] == "2025-11-25"
    assert diagnostic.get("http_status") == (403 if status == 403 else None)
    assert diagnostic.get("parser_code") == (
        "unexpected_content_type" if status == 200 else None
    )
    assert "secret" not in str(error.value) + json.dumps(diagnostic)


@pytest.mark.asyncio
async def test_unknown_outcome_cannot_be_counted_as_a_confirmed_service_effect():
    def handle(request):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json.loads(request.content)["id"],
                "result": {
                    "structuredContent": {"success": True},
                    "_meta": {"ha_mcp": {"status": "outcome_unknown"}},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = Client(
            http, {"url": "http://127.0.0.1:8123/secret", "protocol": "2025-06-18"}, ""
        )
        with pytest.raises(UpgradeFailure, match="mcp_tool_outcome_not_confirmed"):
            await client.call("ha_call_service", {"service": "toggle"})


@pytest.mark.asyncio
async def test_changed_connection_is_rejected_before_any_network_request(tmp_path):
    connection = {"url": "http://127.0.0.1:8123/original"}
    expected = fingerprint(connection)
    connection["url"] = "http://127.0.0.1:8123/rewritten"
    path = tmp_path / "client.json"
    path.write_text(json.dumps(connection))
    http = AsyncMock()
    with pytest.raises(UpgradeFailure, match="client_connection_changed"):
        await exercise.phase(
            http,
            path,
            expected,
            {},
            {},
            _phase(),
            {},
            control=("http://127.0.0.1:8123", "control"),
        )
    assert not http.mock_calls


@pytest.mark.asyncio
async def test_mcp_claimed_effect_must_match_independent_core_state():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"state": "on"})
        )
    ) as http:
        client = AsyncMock()
        client.http = http
        client.call.side_effect = [{"success": True}, {"data": {"state": "off"}}]
        with pytest.raises(UpgradeFailure, match="core_service_effect_not_observed"):
            await exercise.witness(
                client, baseline=True, control=("http://127.0.0.1:8123", "control")
            )
    assert client.call.await_count == 2


@pytest.mark.asyncio
async def test_runtime_attestation_rejects_other_candidate_before_client_use():
    expected = dict.fromkeys(
        (
            "run_nonce",
            "revision",
            "core_image_id",
            "component_sha256",
            "wheel_sha256",
            "package_sha256",
        ),
        "expected",
    )
    observed = {**expected, "running": True, "revision": "substituted"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=observed))
    ) as http:
        with pytest.raises(UpgradeFailure, match="runtime_build_receipt_mismatch"):
            await exercise.ready(
                http, "http://127.0.0.1:8123", "token", expected, "legacy"
            )
