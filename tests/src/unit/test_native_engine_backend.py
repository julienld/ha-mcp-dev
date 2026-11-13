"""Native backend calls Core owners independently of WS registration/adapters."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import voluptuous as _REAL_VOL

from ha_mcp.runtime import Engine
from ha_mcp.runtime.catalog import build_initial_catalog
from ha_mcp.tool_api import (
    CallContext,
    ToolDefinition,
    ToolFailure,
    UnsupportedOperation,
)

from .test_component_helper_collections import (
    FakeCollection,
    FakeRegistry,
    _hass,
    hc,
)
from .test_component_ws_phase2_async import _call_hass, _FakeCallServices
from .test_component_ws_search import FakeState, wsapi


class EventBus:
    def __init__(self) -> None:
        self.listeners: list[Any] = []

    def async_listen(self, event_type: Any, callback: Any) -> Any:
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback)

    def fire(self, state: Any, context: Any) -> None:
        event = SimpleNamespace(
            context=context, data={"entity_id": state.entity_id, "new_state": state}
        )
        for callback in list(self.listeners):
            callback(event)


@pytest.fixture
def native() -> Any:
    """Use Core and the component exactly as imported by the test plugin."""
    return importlib.import_module("custom_components.ha_mcp_tools.native_backend")


def authorize(hass: Any) -> Any:
    user = SimpleNamespace(
        id="actor", is_admin=True, is_active=True, system_generated=False
    )
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(return_value=user))
    return user


@pytest.mark.parametrize("kind", ["automation", "script", "scene"])
async def test_native_core_reference_verdict_reaches_shared_writers(
    native: Any, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from custom_components.ha_mcp_tools import config_references
    from ha_mcp.runtime.config_write_context import ConfigWriteContext

    hass = SimpleNamespace()
    authorize(hass)
    config = {"variables": {"action": "payload.not_a_service"}}
    verdict = {
        "status": "ok",
        "missing": [],
        "mismatches": [
            {
                "path": "actions[0]",
                "name": "select.select_option",
                "entity_id": "input_select.mode",
                "offered": ["input_select.select_option"],
            }
        ],
    }
    owner = AsyncMock(return_value=verdict)
    monkeypatch.setattr(config_references, "async_config_references", owner)
    tools = ConfigWriteContext(native.NativeBackend(hass), CallContext("actor"))
    result = await tools._validate_references(config, kind)
    assert result["warnings"][0]["offered"] == ["input_select.select_option"]
    assert result["warnings"][0]["value"] == "input_select.mode"
    owner.assert_awaited_once_with(hass, {"kind": kind, "config": config})


async def test_native_core_reference_read_refuses_revoked_actor_after_await(
    native: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from custom_components.ha_mcp_tools import config_references

    hass = SimpleNamespace()
    user = authorize(hass)

    async def revoke(_hass: Any, _arguments: Any) -> dict[str, Any]:
        user.is_admin = False
        return {"status": "ok", "missing": [], "mismatches": []}

    monkeypatch.setattr(config_references, "async_config_references", revoke)
    with pytest.raises(PermissionError):
        await native.NativeBackend(hass).execute(
            "config.references.check",
            {"kind": "automation", "config": {}},
            CallContext("actor"),
        )


async def test_native_state_and_service_call_do_not_consult_the_wire_surface(
    native: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire = importlib.import_module("custom_components.ha_mcp_tools.websocket_api")

    def wire_forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Native execution must not consult WebSocket adapters")

    for name in (
        "_command_specs",
        "_do_states",
        "_call_service_prep",
        "_do_call_service",
    ):
        monkeypatch.setattr(wire, name, wire_forbidden)
    services = _FakeCallServices(known={("scene", "turn_on")})
    hass = _call_hass([FakeState("light.a", "on")], services, EventBus())
    authorize(hass)
    backend = native.NativeBackend(hass)
    states = await backend.execute(
        "states.read", {"entity_ids": ["light.a"]}, CallContext("actor")
    )
    result = await backend.execute(
        "services.call_observe",
        {"domain": "scene", "service": "turn_on", "wait": False},
        CallContext("actor"),
    )
    assert states["states"]["light.a"]["state"] == "on"
    assert result["dispatched"] and len(services.calls) == 1
    assert services.calls[0]["context"].user_id == "actor"


async def test_native_catalog_and_entry_reads_do_not_use_async_wire_preparation(
    native: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_component_ws_search import FakeConfigEntries

    wire = importlib.import_module("custom_components.ha_mcp_tools.websocket_api")
    catalogs = importlib.import_module("custom_components.ha_mcp_tools.core_services")
    entries = importlib.import_module(
        "custom_components.ha_mcp_tools.core_config_entries"
    )

    def wire_forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Native reads must not call WS prep/do")

    for name in (
        "_command_specs",
        "_services_list_prep",
        "_do_services_list",
        "_config_entries_prep",
        "_do_config_entries",
    ):
        monkeypatch.setattr(wire, name, wire_forbidden)
    monkeypatch.setattr(
        catalogs,
        "_fetch_service_descriptions",
        AsyncMock(return_value={"light": {"turn_on": {}}}),
    )
    monkeypatch.setattr(
        catalogs, "_fetch_service_translations", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        entries, "_load_secret_scrub", lambda hass: (frozenset(), False)
    )
    hass = _call_hass([], _FakeCallServices(known=set()), EventBus())
    hass.config_entries = FakeConfigEntries([])
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    authorize(hass)
    backend = native.NativeBackend(hass)
    catalog = await backend.execute("services.catalog", {}, CallContext("actor"))
    records = await backend.execute("integrations.entries", {}, CallContext("actor"))
    assert catalog["services"][0]["domain"] == "light"
    assert records == {"entries": []}


async def test_native_service_tool_keeps_all_changed_states_and_actor(
    native: Any,
) -> None:
    bus = EventBus()
    services = _FakeCallServices(known={("scene", "turn_on")})
    hass = _call_hass([], services, bus)
    authorize(hass)

    def changed() -> None:
        context = services.calls[0]["context"]
        bus.fire(FakeState("light.a", "on"), context)
        bus.fire(FakeState("switch.b", "on"), context)
        bus.fire(FakeState("sensor.unrelated", "1"), SimpleNamespace(user_id="other"))

    services._on_call = changed
    backend = native.NativeBackend(hass)
    engine = Engine(backend, build_initial_catalog(backend))
    result = await engine.call(
        "ha_call_service",
        {"domain": "scene", "service": "turn_on", "verbose": True},
        CallContext("actor"),
    )
    assert not result.is_error
    assert [state["entity_id"] for state in result.data["result"]] == [
        "light.a",
        "switch.b",
    ]
    assert services.calls[0]["context"].user_id == "actor"
    assert len(services.calls) == 1 and bus.listeners == []
    assert hass.auth.async_get_user.await_count >= 4


async def test_native_confirmation_registers_before_dispatch(native: Any) -> None:
    bus = EventBus()
    services = _FakeCallServices(known={("light", "turn_on")}, response={"future": 42})
    hass = _call_hass([FakeState("light.a", "off")], services, bus)
    authorize(hass)

    def changed() -> None:
        assert len(bus.listeners) == 1
        bus.fire(
            FakeState("light.a", "on", brightness=255), services.calls[0]["context"]
        )

    services._on_call = changed
    backend = native.NativeBackend(hass)
    result = await Engine(backend, build_initial_catalog(backend)).call(
        "ha_call_service",
        {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.a",
            "return_response": True,
            "result_fields": ["entity_id", "state"],
        },
        CallContext("actor"),
    )
    assert result.data["verified_state"] == "on"
    assert result.data["service_response"] == {"future": 42}
    assert result.data["result"] == [{"entity_id": "light.a", "state": "on"}]
    assert len(services.calls) == 1 and bus.listeners == []


@pytest.mark.parametrize("failure_type", [ValueError, _REAL_VOL.Invalid])
async def test_mutate_then_raise_is_not_reissued(
    native: Any, failure_type: Any
) -> None:
    bus = EventBus()
    services = _FakeCallServices(
        known={("switch", "toggle")}, raises=failure_type("listener failed after write")
    )
    hass = _call_hass([], services, bus)
    authorize(hass)
    backend = native.NativeBackend(hass)
    result = await Engine(backend, build_initial_catalog(backend)).call(
        "ha_call_service",
        {"domain": "switch", "service": "toggle", "wait": False},
        CallContext("actor"),
    )
    assert result.is_error and result.status == "outcome_unknown"
    assert len(services.calls) == 1 and bus.listeners == []


async def test_engine_owned_invalid_core_payload_is_a_definite_rejection(
    native: Any,
) -> None:
    services = _FakeCallServices(known={("light", "turn_on")})
    bus = EventBus()
    hass = _call_hass([], services, bus)
    authorize(hass)
    backend = native.NativeBackend(hass)

    async def invoke(arguments: Any, context: CallContext) -> Any:
        return await backend.execute("services.call_observe", arguments, context)

    tool = ToolDefinition("core_write", "Core write", {"type": "object"}, invoke)
    result = await Engine(backend, [tool]).call(
        "core_write",
        {"domain": "light", "service": "turn_on", "service_data": []},
        CallContext("actor"),
    )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "VALIDATION_FAILED"
    assert services.calls == [] and bus.listeners == []


async def test_core_schema_implementation_failure_is_not_remapped(
    native: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    hass = _hass(FakeCollection())
    authorize(hass)
    failure = RuntimeError("validator implementation failed")

    def broken(_schema: Any) -> Any:
        raise failure

    monkeypatch.setitem(native._CORE_PARAMETERS, "services.call_observe", broken)
    with pytest.raises(RuntimeError) as caught:
        await native.NativeBackend(hass).execute(
            "services.call_observe", {}, CallContext("actor")
        )
    assert caught.value is failure


@pytest.mark.parametrize("helper_type", [None, "unknown_helper"])
async def test_invalid_helper_snapshot_write_is_rejected_before_owner_lookup(
    native: Any, monkeypatch: pytest.MonkeyPatch, helper_type: str | None
) -> None:
    helpers = importlib.import_module(
        "custom_components.ha_mcp_tools.native_operations.helpers"
    )
    owner_lookup = Mock(return_value=None)
    monkeypatch.setattr(helpers, "collection_owner", owner_lookup)
    collection = FakeCollection()
    hass = _hass(collection)
    authorize(hass)
    backend = native.NativeBackend(hass)

    async def invoke(arguments: Any, context: CallContext) -> Any:
        return await backend.execute("helpers.storage.write", arguments, context)

    tool = ToolDefinition("helper_write", "Helper write", {"type": "object"}, invoke)
    arguments: dict[str, Any] = {
        "action": "update",
        "item_id": "test",
        "data": {"name": "Changed"},
        "expected_item": {"id": "test", "name": "Before"},
    }
    if helper_type is not None:
        arguments["helper_type"] = helper_type
    result = await Engine(backend, [tool]).call(
        "helper_write", arguments, CallContext("actor")
    )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "VALIDATION_FAILED"
    owner_lookup.assert_not_called()
    assert collection.data == {}


async def test_idempotent_noop_keeps_confirmed_state_result(native: Any) -> None:
    bus = EventBus()
    services = _FakeCallServices(known={("light", "turn_on")})
    hass = _call_hass([FakeState("light.a", "on")], services, bus)
    authorize(hass)
    backend = native.NativeBackend(hass)
    result = await Engine(backend, build_initial_catalog(backend)).call(
        "ha_call_service",
        {"domain": "light", "service": "turn_on", "entity_id": "light.a"},
        CallContext("actor"),
    )
    assert result.data["verified_state"] == "on"
    assert result.data["result"][0]["entity_id"] == "light.a"
    assert services.call_count == 1 and not bus.listeners


@pytest.mark.parametrize("flag", ["is_active", "is_admin", "system_generated"])
async def test_live_actor_rechecked_before_every_operation(
    native: Any, flag: str
) -> None:
    hass = _hass(FakeCollection())
    user = authorize(hass)
    backend = native.NativeBackend(hass)
    await backend.authorize(CallContext("actor"))
    setattr(user, flag, flag == "system_generated")
    with pytest.raises(PermissionError):
        await backend.execute("states.read", {"entity_ids": []}, CallContext("actor"))


async def test_native_helper_calls_collection_owner_and_reads_back(
    native: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection = FakeCollection()
    registry = FakeRegistry()
    registry.add("input_number.test", "input_number", "test")
    monkeypatch.setattr(wsapi.er, "async_get", lambda hass: registry)
    hass = _hass(collection)
    authorize(hass)
    backend = native.NativeBackend(hass)
    args = {
        "helper_type": "input_number",
        "action": "create",
        "data": {"name": "Test", "future_field": "kept"},
    }
    result = await backend.execute("helpers.storage.write", args, CallContext("actor"))
    readback = await backend.execute(
        "helpers.storage.read",
        {"helper_type": "input_number", "entity_id": "input_number.test"},
        CallContext("actor"),
    )
    assert (
        result["item"]
        == readback["item"]
        == {"id": "test", "name": "Test", "future_field": "kept"}
    )
    assert hc.collection_owner(hass, "input_number").storage_collection is collection


@pytest.mark.parametrize(
    "operation", ["helpers.storage.write", "services.call_observe"]
)
async def test_readonly_core_write_reports_no_dispatch(
    native: Any, operation: str
) -> None:
    collection = FakeCollection()
    hass = _hass(collection)
    authorize(hass)
    backend = native.NativeBackend(hass)
    with pytest.raises(ToolFailure, match="Writes are disabled") as caught:
        await backend.execute(operation, {}, CallContext("actor", read_only=True))
    assert caught.value.code == "READ_ONLY"
    assert caught.value.status == "not_started"
    assert collection.data == {}


async def test_reserved_envelopes_and_unsupported_ops_cannot_reach_owner(
    native: Any,
) -> None:
    collection = FakeCollection()
    hass = _hass(collection)
    authorize(hass)
    backend = native.NativeBackend(hass)
    with pytest.raises(ToolFailure, match="Protected"):
        await backend.execute(
            "states.read", {"type": "call_service"}, CallContext("actor")
        )
    with pytest.raises(UnsupportedOperation):
        await backend.execute("arbitrary/ws_command", {}, CallContext("actor"))
    assert collection.data == {}


async def test_arbitrary_ws_is_explicit_native_incompatibility(native: Any) -> None:
    hass = _hass(FakeCollection())
    authorize(hass)
    backend = native.NativeBackend(hass)
    result = await Engine(backend, build_initial_catalog(backend)).call(
        "ha_call_service", {"ws_command": "repairs/list_issues"}, CallContext("actor")
    )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "UNSUPPORTED_OPERATION"
