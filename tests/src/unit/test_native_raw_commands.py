"""Known raw commands retain Core bodies without creating a transport server."""

import importlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ha_mcp.runtime import Engine
from ha_mcp.runtime.catalog import build_initial_catalog
from ha_mcp.tool_api import CallContext

from .test_component_ws_phase2_async import _call_hass, _FakeCallServices
from .test_native_engine_backend import EventBus, authorize
from .test_native_engine_backend import native as native


@pytest.mark.parametrize("single", [False, True])
async def test_registry_reads_keep_raw_keys_and_isolate_invalid_ids(
    native, monkeypatch, single
):
    owner = importlib.import_module(
        "custom_components.ha_mcp_tools.native_registry_ops"
    )
    helpers = importlib.import_module(
        "custom_components.ha_mcp_tools.helper_collections"
    )
    cv = sys.modules["homeassistant.helpers.config_validation"]
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"], "config_validation", cv, raising=False
    )

    def normalize(raw):
        if raw == "invalid":
            raise helpers._INVALID_ERRORS[0]("Invalid entity ID")
        return raw.strip().lower()

    monkeypatch.setattr(cv, "entity_id", normalize)
    monkeypatch.setattr(
        cv, "entity_ids", lambda values: [normalize(raw) for raw in values]
    )
    rows = {
        "light.kitchen": SimpleNamespace(extended_dict={"entity_id": "light.kitchen"}),
        "sensor.valid": SimpleNamespace(extended_dict={"entity_id": "sensor.valid"}),
    }
    registry = SimpleNamespace(async_get=rows.get)
    registry_module = SimpleNamespace(async_get=lambda _: registry)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", registry_module
    )
    monkeypatch.setattr(
        sys.modules["homeassistant.helpers"], "entity_registry", registry_module
    )
    ids = (
        [" Light.Kitchen "]
        if single
        else [" Light.Kitchen ", "invalid", "sensor.valid", "light.missing"]
    )
    result = await owner._entity_read(object(), {"entity_ids": ids, "single": single})
    expected = {" Light.Kitchen ": {"entity_id": "light.kitchen"}}
    if not single:
        expected["sensor.valid"] = {"entity_id": "sensor.valid"}
    assert result["entries"] == expected
    assert result["errors"] == (
        {}
        if single
        else {"invalid": "Invalid entity ID", "light.missing": "Entity not found"}
    )


async def test_raw_read_after_another_test_preimports_the_serializer(
    monkeypatch, request
):
    raw = importlib.import_module("custom_components.ha_mcp_tools.native_raw_commands")
    monkeypatch.setattr(raw, "json_bytes", Mock())
    native = request.getfixturevalue("native")
    backend, _user = raw_backend(native, ["get_config"])
    body = {"future": {"retained": [1]}}
    backend.hass.config = SimpleNamespace(as_dict=lambda: body)
    engine = Engine(backend, build_initial_catalog(backend))

    result = await engine.call(
        "ha_call_service", {"ws_command": "get_config"}, CallContext("actor")
    )

    assert not result.is_error, result.data
    assert result.data["result"] == body
    result.data["result"]["future"]["retained"].append(2)
    assert body["future"]["retained"] == [1]


async def test_device_listing_keeps_child_devices_and_omits_unserialized_entries(
    native, monkeypatch
):
    visible = {"id": "main", "future": {"retained": True}}
    child = {"id": "child", "main_device": "main"}
    registry = SimpleNamespace(
        devices=[
            SimpleNamespace(json_repr=json.dumps(visible)),
            SimpleNamespace(json_repr=None),
        ],
        child_devices=[SimpleNamespace(json_repr=json.dumps(child))],
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.device_registry",
        SimpleNamespace(async_get=lambda _hass: registry),
    )
    backend, _ = raw_backend(native, ["config/device_registry/list"])
    engine = Engine(backend, build_initial_catalog(backend))

    result = await engine.call(
        "ha_call_service",
        {"ws_command": "config/device_registry/list"},
        CallContext("actor"),
    )

    assert not result.is_error, result.data
    assert result.data["result"] == [visible, child]


def raw_backend(native, commands=()):
    hass = _call_hass([], _FakeCallServices(known=set()), EventBus())
    user = authorize(hass)
    hass.data = {
        "websocket_api": {command: (None, lambda value: value) for command in commands}
    }
    return native.NativeBackend(hass), user


async def test_known_registry_command_retains_future_fields_and_detaches_core_data(
    native, monkeypatch
):
    body = {"area_id": "kitchen", "name": "Kitchen", "future": {"values": [1]}}
    registry = SimpleNamespace(
        async_list_areas=lambda: [SimpleNamespace(json_fragment=body)]
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.area_registry",
        SimpleNamespace(async_get=lambda _hass: registry),
    )
    hass = _call_hass([], _FakeCallServices(known=set()), EventBus())
    authorize(hass)
    validated = []

    def schema(message):
        validated.append(dict(message))
        return message

    hass.data = {"websocket_api": {"config/area_registry/list": (None, schema)}}
    backend = native.NativeBackend(hass)
    engine = Engine(backend, build_initial_catalog(backend))
    result = await engine.call(
        "ha_call_service",
        {"ws_command": "config/area_registry/list"},
        CallContext("actor"),
    )
    assert not result.is_error
    assert result.data["result"] == [body]
    assert validated == [{"id": 1, "type": "config/area_registry/list"}]
    result.data["result"][0]["future"]["values"].append(2)
    assert body["future"]["values"] == [1]


async def test_unknown_command_never_calls_a_registered_extension_handler(native):
    handler = AsyncMock(side_effect=AssertionError("extension dispatched"))

    def validator(message):
        return message

    hass = _call_hass([], _FakeCallServices(known=set()), EventBus())
    authorize(hass)
    hass.data = {"websocket_api": {"custom/arbitrary": (handler, validator)}}
    backend = native.NativeBackend(hass)
    engine = Engine(backend, build_initial_catalog(backend))
    result = await engine.call(
        "ha_call_service", {"ws_command": "custom/arbitrary"}, CallContext("actor")
    )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "UNSUPPORTED_OPERATION"
    handler.assert_not_awaited()


async def test_core_validator_refuses_unknown_command_fields_before_read(
    native, monkeypatch
):
    import voluptuous as _REAL_VOL

    read = AsyncMock(side_effect=AssertionError("owner read after refusal"))
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.area_registry",
        SimpleNamespace(async_get=read),
    )
    hass = _call_hass([], _FakeCallServices(known=set()), EventBus())
    authorize(hass)
    hass.data = {
        "websocket_api": {
            "config/area_registry/list": (
                None,
                _REAL_VOL.Schema({"id": int, "type": str}),
            )
        }
    }
    backend = native.NativeBackend(hass)
    engine = Engine(backend, build_initial_catalog(backend))
    result = await engine.call(
        "ha_call_service",
        {"ws_command": "config/area_registry/list", "data": {"unowned": True}},
        CallContext("actor"),
    )
    assert result.status == "not_started"
    assert result.data["error"]["code"] == "VALIDATION_FAILED"
    read.assert_not_called()


async def test_raw_ws_service_descriptions_keep_the_ws_mapping_and_rest_keeps_its_list(
    native, monkeypatch
):
    descriptions = {"light": {"turn_on": {"future": {"values": [1]}}}}
    rest = [{"domain": "light", "services": descriptions["light"]}]
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.service",
        SimpleNamespace(
            async_get_all_descriptions=AsyncMock(return_value=descriptions)
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.api",
        SimpleNamespace(
            async_services_json=AsyncMock(return_value=rest),
            async_events_json=lambda _hass: [],
        ),
    )
    backend, _user = raw_backend(native, ["get_services"])
    actor = CallContext("actor")
    ws_result = await backend.execute(
        "services.websocket_command", {"ws_command": "get_services"}, actor
    )
    rest_result = await backend.execute("code.api.get", {"path": "services"}, actor)
    assert ws_result["result"] == descriptions
    assert rest_result == rest
    ws_result["result"]["light"]["turn_on"]["future"]["values"].append(2)
    assert descriptions["light"]["turn_on"]["future"]["values"] == [1]


async def test_raw_config_retains_core_fields_and_ws_honors_the_real_local_only_actor(
    native,
):
    backend, user = raw_backend(native, ["get_config"])
    user.local_only = True
    body = {"external_url": "https://ha.example", "future": {"setting": ["value"]}}
    backend.hass.config = SimpleNamespace(as_dict=lambda: body)
    actor = CallContext("actor")
    ws_result = await backend.execute(
        "services.websocket_command", {"ws_command": "get_config"}, actor
    )
    rest_result = await backend.execute("code.api.get", {"path": "config"}, actor)
    assert "external_url" not in ws_result["result"]
    assert rest_result == body
    assert ws_result["result"]["future"] == body["future"]
    assert body["external_url"] == "https://ha.example"


async def test_raw_template_uses_core_text_rendering_and_historical_json_decoding(
    native, monkeypatch
):
    template = SimpleNamespace(
        async_render_will_timeout=AsyncMock(return_value=False),
        async_render=lambda **arguments: (
            '["a", 42]'
            if arguments == {"variables": {"x": 42}, "parse_result": False}
            else "WRONG"
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.api",
        SimpleNamespace(_cached_template=lambda source, _hass: template),
    )
    backend, _user = raw_backend(native)
    result = await backend.execute(
        "code.api.template",
        {"data": {"template": "fixture", "variables": {"x": 42}}},
        CallContext("actor"),
    )
    assert result == ["a", 42]


async def test_raw_read_withholds_provider_data_when_the_real_actor_is_revoked(
    native, monkeypatch
):
    from ha_mcp.tool_api import ToolDefinition

    backend, user = raw_backend(native)

    async def provider(_hass):
        user.is_active = False
        return [{"domain": "private_data"}]

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.api",
        SimpleNamespace(
            async_services_json=provider, async_events_json=lambda _hass: []
        ),
    )

    async def read(_arguments, actor):
        return await backend.execute("code.api.get", {"path": "services"}, actor)

    engine = Engine(
        backend,
        [ToolDefinition("ha_list_services", "Read", {}, read, {"readOnlyHint": True})],
    )
    result = await engine.call("ha_list_services", {}, CallContext("actor"))
    assert result.is_error
    assert "private_data" not in str(result.data)
