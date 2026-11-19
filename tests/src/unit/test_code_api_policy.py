"""Legacy code helpers keep path, protected-write and snapshot policy behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize(
    "endpoint", ["/api/states/sun.sun", "/states/sun.sun", "states/sun.sun"]
)
async def test_legacy_raw_read_keeps_the_historical_relative_endpoint(endpoint):
    from ha_mcp.tools.tools_code import _SandboxBridge

    response = SimpleNamespace(json=lambda: {"entity_id": "sun.sun"})
    client = SimpleNamespace(guarded_request=AsyncMock(return_value=response))
    bridge = _SandboxBridge(None, client, SimpleNamespace(code_mode_max_invocations=10))
    assert await bridge.api_get(endpoint) == {"entity_id": "sun.sun"}
    client.guarded_request.assert_awaited_once_with("GET", "states/sun.sun")


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://external.invalid/config",
        "//external.invalid/config",
        "/api/%2e%2e/auth/providers",
        "/api/..?x=1",
    ],
)
async def test_legacy_raw_endpoint_cannot_escape_ha_api(endpoint):
    from ha_mcp.tools.tools_code import _SandboxBridge

    client = SimpleNamespace(guarded_request=AsyncMock())
    bridge = _SandboxBridge(None, client, SimpleNamespace(code_mode_max_invocations=10))
    assert "error" in await bridge.api_get(endpoint)
    client.guarded_request.assert_not_awaited()


@pytest.mark.parametrize(
    "endpoint",
    [
        "/states/sensor.example",
        "/config/automation/config/known",
        "/events/state_changed",
        "./states/sun.sun",
        "events/state_changed?x=1",
        "events/./state_changed",
        "config/automation/./config/known?x=1",
        "events/%73tate_changed",
    ],
)
async def test_legacy_protected_write_stays_refused_before_request(endpoint):
    from ha_mcp.tools.tools_code import _SandboxBridge

    client = SimpleNamespace(guarded_request=AsyncMock())
    bridge = _SandboxBridge(None, client, SimpleNamespace(code_mode_max_invocations=10))
    assert "error" in await bridge.api_post(endpoint, {})
    client.guarded_request.assert_not_awaited()


async def test_legacy_custom_event_preserves_the_original_query_and_body():
    from ha_mcp.tools.tools_code import _SandboxBridge

    payload = {"value": 42}
    response = SimpleNamespace(json=lambda: {"message": "Event fired"})
    client = SimpleNamespace(guarded_request=AsyncMock(return_value=response))
    bridge = _SandboxBridge(None, client, SimpleNamespace(code_mode_max_invocations=10))
    endpoint = "events/custom_event?x=state_changed&x=%2F"

    assert await bridge.api_post(endpoint, payload) == {"message": "Event fired"}
    client.guarded_request.assert_awaited_once_with("POST", endpoint, json=payload)


async def test_legacy_snapshot_post_keeps_its_existing_control_owner(monkeypatch):
    from ha_mcp.tools import tools_code

    checked = []

    def snapshot_refusal(**arguments):
        checked.append(arguments)
        return "Snapshot action disabled"

    monkeypatch.setattr(tools_code, "snapshot_route_refusal", snapshot_refusal)
    client = SimpleNamespace(guarded_request=AsyncMock())
    bridge = tools_code._SandboxBridge(
        None, client, SimpleNamespace(code_mode_max_invocations=10)
    )
    assert await bridge.api_post("/services/backup/create") == {
        "error": "Snapshot action disabled"
    }
    assert checked == [{"rest_path": "services/backup/create"}]
    client.guarded_request.assert_not_awaited()
