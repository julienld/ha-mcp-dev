"""Native backend ports use actual Core services, states, users and collections."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import voluptuous as vol
from homeassistant.auth.models import User
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.json import json_bytes
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_mcp_tools import config_references, helper_collections
from custom_components.ha_mcp_tools import websocket_api as wire
from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations import helpers
from ha_mcp.runtime import Engine
from ha_mcp.runtime.catalog import build_initial_catalog
from ha_mcp.tool_api import (
    CallContext,
    ToolDefinition,
    ToolFailure,
    UnsupportedOperation,
)


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


def authorize(hass: Any) -> Any:
    user = SimpleNamespace(
        id="actor", is_admin=True, is_active=True, system_generated=False
    )
    hass.auth = SimpleNamespace(async_get_user=AsyncMock(return_value=user))
    return user


@pytest.fixture
def actor(hass_admin_user: User) -> CallContext:
    return CallContext(hass_admin_user.id)


def _engine(hass: HomeAssistant) -> Engine:
    backend = NativeBackend(hass)
    return Engine(backend, build_initial_catalog(backend))


def _register(
    hass: HomeAssistant,
    domain: str,
    service: str,
    action: Callable[[ServiceCall], Awaitable[Any]],
) -> None:
    hass.services.async_register(
        domain, service, action, supports_response=SupportsResponse.OPTIONAL
    )


@pytest.mark.parametrize("kind", ["automation", "script", "scene"])
async def test_native_core_reference_verdict_comes_from_the_core_producer(
    hass: HomeAssistant,
    actor: CallContext,
    kind: str,
) -> None:
    hass.states.async_set("light.present", "off")
    configurations = {
        "automation": {
            "alias": "Probe",
            "trigger": [],
            "action": [{"event": "native_probe"}],
        },
        "script": {
            "sequence": [
                {"variables": {"action": "payload.not_a_service"}},
                {"event": "native_probe"},
            ]
        },
        "scene": {"name": "Probe", "entities": {"light.present": {"state": "on"}}},
    }
    arguments = {"kind": kind, "config": configurations[kind]}
    expected = await config_references.async_config_references(hass, arguments)
    result = await NativeBackend(hass).execute(
        "config.references.check", arguments, actor
    )
    assert result == json.loads(json_bytes(expected))
    assert result["status"] in {"ok", "invalid", "unavailable"}


async def test_native_reference_read_refuses_revocation_after_await(
    hass: HomeAssistant,
    hass_admin_user: User,
    actor: CallContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = config_references.async_config_references

    async def revoke(core: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await read(core, arguments)
        await hass.auth.async_update_user(hass_admin_user, is_active=False)
        return result

    monkeypatch.setattr(config_references, "async_config_references", revoke)
    with pytest.raises(PermissionError):
        await NativeBackend(hass).execute(
            "config.references.check",
            {"kind": "script", "config": {"sequence": []}},
            actor,
        )


async def test_native_state_and_service_do_not_consult_wire_adapters(
    hass: HomeAssistant,
    actor: CallContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Native execution consulted a WebSocket adapter")

    for name in (
        "_command_specs",
        "_do_states",
        "_call_service_prep",
        "_do_call_service",
    ):
        monkeypatch.setattr(wire, name, forbidden)
    calls: list[ServiceCall] = []

    async def turn_on(call: ServiceCall) -> None:
        calls.append(call)

    _register(hass, "scene", "turn_on", turn_on)
    hass.states.async_set("light.a", "on")
    backend = NativeBackend(hass)
    states = await backend.execute("states.read", {"entity_ids": ["light.a"]}, actor)
    result = await backend.execute(
        "services.call_observe",
        {"domain": "scene", "service": "turn_on", "wait": False},
        actor,
    )
    assert states["states"]["light.a"]["state"] == "on"
    assert result["dispatched"] and len(calls) == 1
    assert calls[0].context.user_id == actor.user_id


async def test_native_catalog_and_config_entries_read_core_owners(
    hass: HomeAssistant,
    actor: CallContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await async_setup_component(hass, "input_boolean", {})
    entry = MockConfigEntry(domain="input_boolean", title="Fixture")
    entry.add_to_hass(hass)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Native reads consulted a WebSocket adapter")

    for name in (
        "_services_list_prep",
        "_do_services_list",
        "_config_entries_prep",
        "_do_config_entries",
    ):
        monkeypatch.setattr(wire, name, forbidden)
    backend = NativeBackend(hass)
    catalog = await backend.execute("services.catalog", {}, actor)
    records = await backend.execute("integrations.entries", {}, actor)
    assert any(row["domain"] == "input_boolean" for row in catalog["services"])
    assert any(row["entry_id"] == entry.entry_id for row in records["entries"])


async def test_native_service_keeps_changed_states_and_actual_core_actor(
    hass: HomeAssistant,
    actor: CallContext,
) -> None:
    calls: list[ServiceCall] = []
    before = hass.bus.async_listeners()

    async def turn_on(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set("light.a", "on", context=call.context)
        hass.states.async_set("switch.b", "on", context=call.context)
        hass.states.async_set("sensor.unrelated", "1", context=Context(user_id="other"))

    _register(hass, "scene", "turn_on", turn_on)
    result = await _engine(hass).call(
        "ha_call_service",
        {"domain": "scene", "service": "turn_on", "verbose": True},
        actor,
    )
    assert not result.is_error, result.data
    assert [row["entity_id"] for row in result.data["result"]] == [
        "light.a",
        "switch.b",
    ]
    assert len(calls) == 1 and calls[0].context.user_id == actor.user_id
    assert hass.bus.async_listeners() == before


async def test_native_confirmation_is_listening_before_core_dispatch(
    hass: HomeAssistant,
    actor: CallContext,
) -> None:
    before = hass.bus.async_listeners().get(EVENT_STATE_CHANGED, 0)
    hass.states.async_set("light.a", "off")
    calls: list[ServiceCall] = []

    async def turn_on(call: ServiceCall) -> dict[str, Any]:
        assert hass.bus.async_listeners().get(EVENT_STATE_CHANGED, 0) > before
        calls.append(call)
        hass.states.async_set(
            "light.a", "on", {"brightness": 255}, context=call.context
        )
        return {"future": 42}

    _register(hass, "light", "turn_on", turn_on)
    result = await _engine(hass).call(
        "ha_call_service",
        {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.a",
            "return_response": True,
            "result_fields": ["entity_id", "state"],
        },
        actor,
    )
    assert not result.is_error, result.data
    assert result.data["verified_state"] == "on"
    assert result.data["service_response"] == {"future": 42}
    assert result.data["result"] == [{"entity_id": "light.a", "state": "on"}]
    assert len(calls) == 1
    assert hass.bus.async_listeners().get(EVENT_STATE_CHANGED, 0) == before


@pytest.mark.parametrize("failure_type", [ValueError, vol.Invalid])
async def test_mutate_then_raise_is_not_reissued(
    hass: HomeAssistant,
    actor: CallContext,
    failure_type: type[Exception],
) -> None:
    calls: list[ServiceCall] = []

    async def toggle(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set("switch.a", "on", context=call.context)
        raise failure_type("listener failed after write")

    _register(hass, "switch", "toggle", toggle)
    result = await _engine(hass).call(
        "ha_call_service",
        {"domain": "switch", "service": "toggle", "wait": False},
        actor,
    )
    assert result.is_error and result.status == "outcome_unknown", result.data
    assert hass.states.get("switch.a").state == "on"
    assert len(calls) == 1


async def test_invalid_core_payload_is_rejected_before_any_dispatch(
    hass: HomeAssistant,
    actor: CallContext,
) -> None:
    backend = NativeBackend(hass)

    async def invoke(arguments: dict[str, Any], context: CallContext) -> Any:
        return await backend.execute("services.call_observe", arguments, context)

    definition = ToolDefinition("core_write", "Core write", {"type": "object"}, invoke)
    result = await Engine(backend, [definition]).call(
        "core_write",
        {"domain": "light", "service": "turn_on", "service_data": []},
        actor,
    )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "VALIDATION_FAILED"
    assert hass.states.get("light.a") is None


async def test_schema_implementation_failure_is_not_remapped(
    hass: HomeAssistant,
    actor: CallContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("validator implementation failed")

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise failure

    backend = NativeBackend(hass)
    with monkeypatch.context() as scoped:
        scoped.setattr(vol.Schema, "__call__", broken)
        with pytest.raises(RuntimeError) as caught:
            await backend.execute(
                "services.call_observe",
                {"domain": "light", "service": "turn_on"},
                actor,
            )
    assert caught.value is failure


@pytest.mark.parametrize("helper_type", [None, "unknown_helper"])
async def test_invalid_helper_snapshot_write_precedes_owner_lookup(
    hass: HomeAssistant,
    actor: CallContext,
    monkeypatch: pytest.MonkeyPatch,
    helper_type: str | None,
) -> None:
    lookup = Mock()
    monkeypatch.setattr(helpers, "collection_owner", lookup)
    arguments: dict[str, Any] = {
        "action": "update",
        "item_id": "test",
        "data": {"name": "Changed"},
        "expected_item": {"id": "test", "name": "Before"},
    }
    if helper_type is not None:
        arguments["helper_type"] = helper_type
    with pytest.raises(ToolFailure) as caught:
        await NativeBackend(hass).execute("helpers.storage.write", arguments, actor)
    assert caught.value.code == "VALIDATION_FAILED"
    lookup.assert_not_called()


async def test_idempotent_noop_retains_confirmed_core_state(
    hass: HomeAssistant,
    actor: CallContext,
) -> None:
    hass.states.async_set("light.a", "on")
    calls: list[ServiceCall] = []

    async def turn_on(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set("light.a", "on", context=call.context)

    _register(hass, "light", "turn_on", turn_on)
    result = await _engine(hass).call(
        "ha_call_service",
        {"domain": "light", "service": "turn_on", "entity_id": "light.a"},
        actor,
    )
    assert not result.is_error, result.data
    assert result.data["verified_state"] == "on"
    assert result.data["result"][0]["entity_id"] == "light.a"
    assert len(calls) == 1


@pytest.mark.parametrize("flag", ["is_active", "is_admin", "system_generated"])
async def test_live_actor_is_rechecked_before_every_operation(
    hass: HomeAssistant,
    hass_admin_user: User,
    actor: CallContext,
    flag: str,
) -> None:
    backend = NativeBackend(hass)
    await backend.authorize(actor)
    if flag == "is_admin":
        await hass.auth.async_update_user(hass_admin_user, group_ids=[])
    elif flag == "is_active":
        await hass.auth.async_update_user(hass_admin_user, is_active=False)
    else:
        hass_admin_user.system_generated = True
    with pytest.raises(PermissionError):
        await backend.execute("states.read", {"entity_ids": []}, actor)


async def test_native_helper_uses_actual_collection_and_reads_back_core_item(
    hass: HomeAssistant,
    actor: CallContext,
) -> None:
    assert await async_setup_component(hass, "input_number", {})
    backend = NativeBackend(hass)
    result = await backend.execute(
        "helpers.storage.write",
        {
            "helper_type": "input_number",
            "action": "create",
            "data": {"name": "Test", "min": 0, "max": 100},
        },
        actor,
    )
    await hass.async_block_till_done()
    identifier = result["item"]["id"]
    readback = await backend.execute(
        "helpers.storage.read",
        {"helper_type": "input_number", "entity_id": f"input_number.{identifier}"},
        actor,
    )
    assert readback["item"] == result["item"]
    assert readback["item"]["min"] == 0 and readback["item"]["max"] == 100
    owner = helper_collections.collection_owner(hass, "input_number")
    assert owner.storage_collection.data[identifier] == readback["item"]


@pytest.mark.parametrize(
    "operation", ["helpers.storage.write", "services.call_observe"]
)
async def test_read_only_write_is_refused_before_core_validation(
    hass: HomeAssistant,
    actor: CallContext,
    operation: str,
) -> None:
    readonly = CallContext(actor.user_id, read_only=True)
    with pytest.raises(ToolFailure) as caught:
        await NativeBackend(hass).execute(operation, {}, readonly)
    assert caught.value.code == "READ_ONLY"
    assert caught.value.status == "not_started"


async def test_reserved_envelopes_and_unsupported_ops_cannot_reach_owner(
    hass: HomeAssistant,
    actor: CallContext,
) -> None:
    backend = NativeBackend(hass)
    with pytest.raises(ToolFailure, match="Protected"):
        await backend.execute("states.read", {"type": "call_service"}, actor)
    with pytest.raises(UnsupportedOperation):
        await backend.execute("arbitrary/ws_command", {}, actor)


async def test_unrecognized_raw_ws_is_explicit_native_incompatibility(
    hass: HomeAssistant,
    actor: CallContext,
) -> None:
    result = await _engine(hass).call(
        "ha_call_service", {"ws_command": "fixture/unknown_command"}, actor
    )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "UNSUPPORTED_OPERATION"
