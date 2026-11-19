"""Raw Native commands are checked against the actual Core owners and wire API."""

import json
from typing import Any
from unittest.mock import Mock

import pytest
import voluptuous as vol
from homeassistant.auth.models import User
from homeassistant.components import api
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.runtime import Engine
from ha_mcp.tool_api import CallContext, ToolDefinition

from ._client_spies import sent_commands
from ._command_faults import pooled_socket
from ._native_core_backend import backend as backend
from ._native_test_engine import native_engine


@pytest.mark.parametrize("single", [False, True])
async def test_registry_reads_keep_raw_keys_and_isolate_invalid_ids(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    entity_registry: er.EntityRegistry,
    single: bool,
) -> None:
    first = entity_registry.async_get_or_create("light", "test", "kitchen")
    second = entity_registry.async_get_or_create("sensor", "test", "valid")
    ids = (
        [first.entity_id]
        if single
        else [first.entity_id.upper(), "invalid", second.entity_id, "light.missing"]
    )
    expected, errors = {}, {}
    for raw in ids:
        try:
            normalized = cv.entity_id(raw)
        except vol.Invalid as error:
            errors[raw] = str(error)
        else:
            row = entity_registry.async_get(normalized)
            if row is None:
                errors[raw] = "Entity not found"
            else:
                expected[raw] = row.extended_dict
    result = await backend.execute(
        "entities.registry.read",
        {"entity_ids": ids, "single": single},
        CallContext(hass_admin_user.id),
    )
    assert result == {"entries": expected, "errors": errors}


async def test_raw_config_remains_detached_with_core_serializer_already_loaded(
    hass_admin_user: User,
    backend: NativeBackend,
    core_client: HomeAssistantClient,
) -> None:
    socket = await pooled_socket(core_client)
    expected = await core_client.send_websocket_message({"type": "get_config"})
    with sent_commands(socket) as sent:
        result = await native_engine(backend).call(
            "ha_call_service",
            {"ws_command": "get_config"},
            CallContext(hass_admin_user.id),
        )
    assert not result.is_error, result.data
    assert result.data["result"] == expected["result"]
    sent.assert_not_called()
    result.data["result"]["components"].append("native.detached_result")
    again = await core_client.send_websocket_message({"type": "get_config"})
    assert "native.detached_result" not in again["result"]["components"]


async def test_device_listing_keeps_real_main_and_child_devices(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    core_client: HomeAssistantClient,
    device_registry: dr.DeviceRegistry,
) -> None:
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    parent = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "parent")}, name="Main"
    )
    child = device_registry.async_get_or_create_child(
        config_entry_id=entry.entry_id,
        identifiers={("test", "child")},
        parent_device_id=parent.id,
    )
    expected = await core_client.send_websocket_message(
        {"type": "config/device_registry/list"}
    )
    result = await native_engine(backend).call(
        "ha_call_service",
        {"ws_command": "config/device_registry/list"},
        CallContext(hass_admin_user.id),
    )
    assert not result.is_error, result.data
    assert result.data["result"] == expected["result"]
    assert {row["id"] for row in result.data["result"]} == {parent.id, child.id}


async def test_known_registry_command_keeps_core_fields_and_detaches_data(
    hass_admin_user: User,
    backend: NativeBackend,
    core_client: HomeAssistantClient,
    area_registry: ar.AreaRegistry,
) -> None:
    area = area_registry.async_create("Kitchen", aliases={"studio"})
    expected = await core_client.send_websocket_message(
        {"type": "config/area_registry/list"}
    )
    result = await native_engine(backend).call(
        "ha_call_service",
        {"ws_command": "config/area_registry/list"},
        CallContext(hass_admin_user.id),
    )
    assert not result.is_error, result.data
    assert result.data["result"] == expected["result"]
    result.data["result"][0]["aliases"].append("result only")
    stored = area_registry.async_get_area(area.id)
    assert stored is not None and stored.aliases == {"studio"}


async def test_a_loaded_core_command_outside_the_boundary_is_not_dispatched(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    core_client: HomeAssistantClient,
) -> None:
    assert await async_setup_component(
        hass, "lovelace", {"lovelace": {"mode": "storage"}}
    )
    assert "lovelace/config" in hass.data["websocket_api"]
    socket = await pooled_socket(core_client)
    with sent_commands(socket) as sent:
        result = await native_engine(backend).call(
            "ha_call_service",
            {"ws_command": "lovelace/config"},
            CallContext(hass_admin_user.id),
        )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "UNSUPPORTED_OPERATION"
    sent.assert_not_called()


async def test_core_validator_refuses_unknown_command_fields_before_read(
    hass_admin_user: User,
    backend: NativeBackend,
    area_registry: ar.AreaRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = Mock(wraps=area_registry.async_list_areas)
    monkeypatch.setattr(area_registry, "async_list_areas", read)
    result = await native_engine(backend).call(
        "ha_call_service",
        {"ws_command": "config/area_registry/list", "data": {"unowned": True}},
        CallContext(hass_admin_user.id),
    )
    assert result.status == "not_started"
    assert result.data["error"]["code"] == "VALIDATION_FAILED"
    read.assert_not_called()


async def test_raw_ws_and_rest_keep_their_core_service_description_shapes(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    core_client: HomeAssistantClient,
) -> None:
    async def probe(call: ServiceCall) -> None:
        return None

    hass.services.async_register("homeassistant", "native_probe", probe)
    expected_ws = await core_client.send_websocket_message({"type": "get_services"})
    expected_rest = await core_client.get_services()
    actor = CallContext(hass_admin_user.id)
    ws_result = await backend.execute(
        "services.websocket_command", {"ws_command": "get_services"}, actor
    )
    rest_result = await backend.execute("code.api.get", {"path": "services"}, actor)
    assert ws_result["result"] == expected_ws["result"]
    assert rest_result == expected_rest
    ws_result["result"]["homeassistant"]["native_probe"]["result_only"] = True
    again = await core_client.send_websocket_message({"type": "get_services"})
    assert "result_only" not in again["result"]["homeassistant"]["native_probe"]


async def test_raw_config_honors_the_actual_local_only_user(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    core_client: HomeAssistantClient,
) -> None:
    await hass.config.async_update(external_url="https://ha.example")
    await hass.auth.async_update_user(hass_admin_user, local_only=True)
    actor = CallContext(hass_admin_user.id)
    expected = await core_client.send_websocket_message({"type": "get_config"})
    ws_result = await backend.execute(
        "services.websocket_command", {"ws_command": "get_config"}, actor
    )
    rest_result = await backend.execute("code.api.get", {"path": "config"}, actor)
    assert ws_result["result"] == expected["result"]
    assert "external_url" not in ws_result["result"]
    assert rest_result == json.loads(json.dumps(hass.config.as_dict()))
    assert rest_result["external_url"] == "https://ha.example"


async def test_raw_template_uses_core_rendering_and_historical_json_decoding(
    hass_admin_user: User,
    backend: NativeBackend,
    core_client: HomeAssistantClient,
) -> None:
    source = "{{ ['a', x] | to_json }}"
    response = await core_client.guarded_request(
        "POST", "/template", json={"template": source, "variables": {"x": 42}}
    )
    response.raise_for_status()
    expected = response.json()
    result = await backend.execute(
        "code.api.template",
        {"data": {"template": source, "variables": {"x": 42}}},
        CallContext(hass_admin_user.id),
    )
    assert result == expected == ["a", 42]


async def test_raw_read_withholds_actual_core_data_after_the_actor_is_revoked(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await async_setup_component(hass, "api", {})

    async def probe(call: ServiceCall) -> None:
        return None

    hass.services.async_register("homeassistant", "native_private_probe", probe)
    original = api.async_services_json

    async def revoke_after_read(core: HomeAssistant) -> Any:
        result = await original(core)
        assert "native_private_probe" in str(result)
        await core.auth.async_update_user(hass_admin_user, is_active=False)
        return result

    monkeypatch.setattr(api, "async_services_json", revoke_after_read)

    async def read(arguments: dict[str, Any], actor: CallContext) -> Any:
        return await backend.execute("code.api.get", {"path": "services"}, actor)

    engine = Engine(
        backend,
        [ToolDefinition("ha_list_services", "Read", {}, read, {"readOnlyHint": True})],
    )
    result = await engine.call("ha_list_services", {}, CallContext(hass_admin_user.id))
    assert result.is_error
    assert "native_private_probe" not in str(result.data)
