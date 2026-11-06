"""Qualification must handle prerelease Core and stop stalled child processes."""

import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "native"))
    return importlib.import_module("run_container")


@pytest.mark.parametrize(
    ("version", "modern"),
    [
        ("2026.9.9", False),
        ("2026.10.0", True),
        ("2026.10.4", True),
        ("2026.11.0b2", True),
        ("2026.11.0.dev202610310001", True),
    ],
)
async def test_oauth_qualification_selects_login_for_prerelease_core(
    harness, version, modern
):
    oauth = importlib.import_module("oauth_checks")
    checks = SimpleNamespace(
        control=AsyncMock(return_value={"versions": {"homeassistant": version}})
    )
    assert await oauth._supports_new_login(checks) is modern


def test_short_docker_operations_have_a_finite_deadline(harness, monkeypatch):
    def run(command, **kwargs):
        assert 0 < kwargs.get("timeout", float("inf")) < float("inf")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(harness.subprocess, "run", run)
    harness.docker("inspect", "fixture")


@pytest.mark.parametrize(
    "probe", ["exercise_external_clients", "exercise_standard_proxy"]
)
async def test_external_probe_timeout_propagates_without_retry(
    harness, monkeypatch, probe
):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        timeout = kwargs.get("timeout", float("inf"))
        assert 0 < timeout < float("inf")
        raise subprocess.TimeoutExpired("disposable probe", timeout)

    monkeypatch.setattr(harness.subprocess, "run", run)
    checks = SimpleNamespace(
        path="/fixture",
        credentials={"alpha": {"access_token": "disposable"}},
        passed=Mock(),
    )
    args = (
        (checks, "fixture-user") if probe == "exercise_external_clients" else (checks,)
    )
    with pytest.raises(subprocess.TimeoutExpired):
        await getattr(harness, probe)(*args)
    assert len(calls) == 1
    checks.passed.assert_not_called()


@pytest.mark.parametrize("phase", ["run", "readiness", "logs"])
async def test_container_is_removed_even_when_startup_or_log_capture_times_out(
    harness, monkeypatch, tmp_path, phase
):
    calls = []

    def docker(command, *args, **kwargs):
        calls.append(command)
        if command == phase:
            raise subprocess.TimeoutExpired("disposable container", 1)
        return subprocess.CompletedProcess([command], 0, "", "")

    monkeypatch.setattr(harness, "CONFIG", tmp_path / "config")
    monkeypatch.setattr(harness, "OUT", tmp_path / "out")
    monkeypatch.setattr(harness, "docker", docker)
    monkeypatch.setattr(
        harness,
        "wait_identities",
        AsyncMock(side_effect=subprocess.TimeoutExpired("readiness", 1)),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        await harness.main()
    assert calls.count("run") == 1
    assert calls[-1] == "rm"


@pytest.mark.parametrize(
    "method,params",
    [
        ("server/discover", {}),
        ("tools/call", {"name": "framing_read", "arguments": {}}),
        ("resources/read", {"uri": "probe://frame/value"}),
    ],
)
async def test_raw_modern_bench_framing_reaches_the_real_sdk_router(
    harness, method, params
):
    import json

    import httpx

    from ha_mcp._vendor.fastmcp import FastMCP

    server = FastMCP("Framing probe", instructions="Exact framing instructions")

    @server.tool()
    async def framing_read() -> dict:
        return {"ready": True}

    @server.resource("probe://frame/value")
    async def framing_resource() -> str:
        return "ready"

    app = server.http_app(
        path="/mcp", stateless_http=True, host_origin_protection=False
    )
    sent = []

    async def record(request):
        sent.append((request.headers, json.loads(request.content)))

    async with (
        app.lifespan(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), event_hooks={"request": [record]}
        ) as client,
    ):
        checks = harness.Checks(client, {"alpha": {"access_token": "fixture-token"}})
        checks.path = "/mcp"
        result = await checks.rpc(method, params)
    assert "error" not in result, result
    headers, body = sent[-1]
    assert (
        headers.get("mcp-protocol-version")
        == body["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"]
    )
    assert headers["mcp-method"] == method
    if method == "server/discover":
        assert result["result"]["instructions"] == "Exact framing instructions"
    else:
        assert (
            headers["mcp-name"]
            == params["uri" if method == "resources/read" else "name"]
        )


async def test_raw_legacy_bench_initialize_omits_the_modern_header(harness):
    import httpx

    from ha_mcp._vendor.fastmcp import FastMCP

    server = FastMCP("Legacy framing probe")
    app = server.http_app(
        path="/mcp", stateless_http=True, host_origin_protection=False
    )
    async with (
        app.lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app)) as client,
    ):
        checks = harness.Checks(client, {"alpha": {"access_token": "fixture-token"}})
        headers = checks.headers(method="initialize", modern=False)
        assert "Mcp-Protocol-Version" not in headers
        response = await client.post(
            "http://fixture/mcp",
            headers=headers,
            json=harness.message(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "legacy-fixture", "version": "1"},
                },
                modern=False,
            ),
        )
        body = harness.unpack(response)
    assert body["result"]["protocolVersion"] == "2025-11-25", body
