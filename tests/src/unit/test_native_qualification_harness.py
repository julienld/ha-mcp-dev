"""Qualification must handle prerelease Core and stop stalled child processes."""

import importlib
import importlib.util
import subprocess
import sys
from contextlib import nullcontext
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


async def test_entity_bench_finds_pre_rename_history_by_public_entity_id(
    harness, monkeypatch, tmp_path
):
    import httpx

    from ha_mcp.runtime.snapshot_store import SnapshotStore

    entities = importlib.import_module("entity_checks")
    entity_id = "sensor.original"
    registry_id = "stable-registry-uuid"
    before = {
        "id": registry_id,
        "entity_id": entity_id,
        "platform": "native_fixture",
        "device_id": "fixture-device",
    }
    renamed = {
        **before,
        "entity_id": entity_id + "_renamed",
        "name": "Native entity settings",
        "icon": "mdi:flash",
        "hidden_by": "user",
        "aliases": ["Native entity alias"],
        "options": {"sensor": {"display_precision": 2}},
    }
    store = SnapshotStore(tmp_path)
    snapshot = store.capture("entity", entity_id, before, "ha_set_entity")
    store.capture("entity", "sensor.unrelated", before, "ha_set_entity")
    assert snapshot is not None

    def respond(request):
        if request.url.path.endswith("/diff"):
            assert request.url.path.endswith("/" + snapshot.name + "/diff")
            return httpx.Response(200, text="Native entity settings")
        return httpx.Response(
            200, json={"backups": store.list_snapshots(**dict(request.url.params))}
        )

    class SnapshotSelected(Exception):
        pass

    async def stop_before_restore(checks, panel, name):
        assert name == snapshot.name
        raise SnapshotSelected

    monkeypatch.setattr(entities, "_restore", stop_before_restore)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://fixture"
    ) as client:
        checks = SimpleNamespace(
            client=client,
            call=AsyncMock(
                side_effect=[
                    {"success": True},
                    {"success": True, "entity_id": renamed["entity_id"]},
                ]
            ),
            control=AsyncMock(
                side_effect=[
                    {
                        "registry_entry": row,
                        "registry_id": registry_id,
                        "entity_id": row["entity_id"],
                        "state": {"state": "on"},
                    }
                    for row in (before, renamed)
                ]
            ),
            passed=Mock(),
        )
        with pytest.raises(SnapshotSelected):
            await entities.exercise_entities(checks, "http://fixture")


async def test_cold_resource_qualification_precedes_clients_that_can_load_core(
    harness, monkeypatch
):
    domain_tools = harness.exercise_domain_tools
    for name in vars(harness):
        if name.startswith("exercise_") and name not in {
            "exercise_runtime",
            "exercise_domain_tools",
        }:
            monkeypatch.setattr(harness, name, AsyncMock(return_value={}))

    loaded = False
    cold_checks = []

    async def dashboards(*args):
        assert loaded is False, "Cold Lovelace checks ran after unrelated readers"
        cold_checks.append("dashboards")

    async def resources(*args):
        nonlocal loaded
        assert loaded is False
        loaded = True
        cold_checks.append("resources")

    async def cards(*args):
        assert loaded is True
        cold_checks.append("cards")

    async def external(*args):
        nonlocal loaded
        loaded = True

    async def exercise(checks, **kwargs):
        await domain_tools(checks)
        return {"ready": True}

    monkeypatch.setattr(harness, "exercise_dashboards", dashboards)
    monkeypatch.setattr(harness, "exercise_resources", resources)
    monkeypatch.setattr(harness, "exercise_dashboard_card_types", cards)
    monkeypatch.setattr(harness, "exercise_external_clients", external)
    monkeypatch.setattr(harness, "exercise", exercise)
    monkeypatch.setattr(harness, "blueprint_source", lambda _: nullcontext("fixture"))
    monkeypatch.setattr(
        harness,
        "docker",
        Mock(
            return_value=SimpleNamespace(
                stdout='[{"NetworkSettings":{"Networks":{"bridge":{"Gateway":"fixture"}}}}]'
            )
        ),
    )
    result = await harness.exercise_runtime(SimpleNamespace(), "fixture-user")
    assert result == {"ready": True}
    assert cold_checks == ["dashboards", "resources", "cards"]


@pytest.mark.parametrize("fails", [False, True])
async def test_resource_load_observer_preserves_core_result_and_failure(
    harness, monkeypatch, fails
):
    from pathlib import Path

    path = (
        Path(harness.__file__).parent / "fixtures/native_fixture/resource_load_probe.py"
    )
    spec = importlib.util.spec_from_file_location("_resource_load_observer", path)
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    failure = RuntimeError("private fixture detail")
    calls = []

    class CoreResources:
        loaded = False

        async def _async_ensure_loaded(self):
            calls.append(self)
            self.loaded = True
            if fails:
                raise failure
            return "original-result"

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.lovelace.resources",
        SimpleNamespace(ResourceStorageCollection=CoreResources),
    )
    owner = CoreResources()
    data = {}
    hass = SimpleNamespace(data={"lovelace": SimpleNamespace(resources=owner)})
    observer.observe_resource_loading(hass, data)
    if fails:
        with pytest.raises(RuntimeError) as raised:
            await owner._async_ensure_loaded()
        assert raised.value is failure
    else:
        assert await owner._async_ensure_loaded() == "original-result"
    assert calls == [owner] and owner.loaded is True
    probe = data["resource_load_probe"]
    assert probe["initial_loaded"] is False
    first = probe["first_load"]
    assert first["loaded_before"] is False and first["loaded_after"] is True
    assert any(row["function"] == "observed" for row in first["stack"])
    assert "private fixture detail" not in str(probe)
