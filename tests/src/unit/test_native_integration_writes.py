"""The real shared integration router drives only owned Core operations."""

import copy
import importlib
import sys
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ha_mcp.runtime import Engine
from ha_mcp.runtime.catalog import define_tool
from ha_mcp.runtime.integration_writes import (
    IntegrationWriteTools,
    integration_changes_state,
)
from ha_mcp.tool_api import CallContext, ToolFailure

from ._native_backend_module import native as native
from .test_component_ws_search import FakeEntityReg, FakeRegEntry, make_view, wsapi
from .test_native_engine_flows import flows as flows
from .test_native_engine_full_flows import _setup


def _integration(native: Any, monkeypatch: pytest.MonkeyPatch, backup: Any) -> tuple:
    hass, user, entry, manager, backend, _ = _setup(native, monkeypatch, backup=backup)
    entry.domain = "demo"
    entry.unique_id = "stable-identity"
    entry.as_json_fragment.update(
        domain="demo", supports_reconfigure=True, supports_options=True, state="loaded"
    )
    row = FakeRegEntry(
        "sensor.example",
        platform="demo",
        config_entry_id="entry",
        unique_id="entity-identity",
    )
    registry = FakeEntityReg({row.entity_id: row})
    monkeypatch.setattr(wsapi.er, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        wsapi.er,
        "async_entries_for_config_entry",
        lambda reg, key: [row] if key == "entry" else [],
        raising=False,
    )
    view = make_view(entity={row.entity_id: row})
    monkeypatch.setattr(wsapi, "_resolve_registries", lambda _hass: view)
    hass.config_entries.async_entries = lambda domain=None: (
        [entry] if domain in {None, "demo"} else []
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.config.config_entries",
        SimpleNamespace(
            _async_matching_config_entries_json_fragments=AsyncMock(
                side_effect=lambda *_args: [copy.deepcopy(entry.as_json_fragment)]
            ),
        ),
    )
    callbacks = []

    def connect(_hass: Any, _signal: Any, function: Any) -> Any:
        callbacks.append(function)
        return lambda: callbacks.remove(function)

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.config_entries",
        SimpleNamespace(SIGNAL_CONFIG_ENTRY_CHANGED="entry_changed"),
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.dispatcher",
        SimpleNamespace(async_dispatcher_connect=connect),
    )
    watcher = importlib.import_module(
        "custom_components.ha_mcp_tools.native_operations.entry_watches"
    )
    monkeypatch.setattr(watcher, "callback", lambda function: function)
    engine = Engine(
        backend,
        [
            define_tool(
                backend,
                IntegrationWriteTools,
                "ha_set_integration",
                annotations={"readOnlyHint": False},
                writes=integration_changes_state,
            )
        ],
    )
    return engine, entry, manager, callbacks, user


@pytest.mark.parametrize("read_only", [False, True])
async def test_native_reconfigure_opens_an_owned_step_and_refuses_readonly(
    native, flows, monkeypatch, read_only
):
    backup = AsyncMock(return_value={})
    engine, _, manager, callbacks, _ = _integration(native, monkeypatch, backup)
    manager.async_init.return_value = {
        "flow_id": "change",
        "type": "form",
        "step_id": "reconfigure",
        "data_schema": [{"name": "host", "required": True}],
    }
    try:
        arguments = {"entry_id": "entry", "reconfigure": True}
        if read_only:
            with pytest.raises(ToolFailure, match="Writes are disabled"):
                await engine.call(
                    "ha_set_integration",
                    arguments,
                    CallContext("actor", read_only=True),
                )
            manager.async_init.assert_not_awaited()
            backup.assert_not_awaited()
        else:
            result = await engine.call(
                "ha_set_integration", arguments, CallContext("actor")
            )
            assert not result.is_error, result.data
            assert result.data["flow_id"] == "change"
            assert "confirm_token" not in result.data
            manager.async_configure.assert_not_awaited()
            backup.assert_awaited_once()
        assert not callbacks
    finally:
        await engine.backend.stop()


@pytest.mark.parametrize("during_backup", ["unchanged", "revision", "revoked"])
async def test_native_reconfigure_step_captures_once_and_observes_its_reload(
    native: Any, flows: Any, monkeypatch: pytest.MonkeyPatch, during_backup: str
) -> None:
    captures = []

    async def backup(payload: dict, _actor: CallContext) -> dict:
        captures.append(copy.deepcopy(payload))
        if during_backup == "revision":
            entry.modified_at += timedelta(seconds=1)
            entry.as_json_fragment["modified_at"] = entry.modified_at.timestamp()
        elif during_backup == "revoked":
            user.is_active = False
        return {}

    engine, entry, manager, callbacks, user = _integration(native, monkeypatch, backup)
    arguments = {
        "entry_id": "entry",
        "reconfigure": True,
        "config": {"host": "192.0.2.10"},
    }
    manager.async_init.return_value = {
        "flow_id": "change",
        "type": "form",
        "step_id": "reconfigure",
        "data_schema": [{"name": "host", "required": True}],
    }

    async def apply(_flow_id: str, user_input: dict) -> dict:
        assert user_input == {"host": "192.0.2.10"}
        entry.modified_at += timedelta(seconds=1)
        entry.as_json_fragment["modified_at"] = entry.modified_at.timestamp()
        for state in ("loaded", "unload_in_progress", "loaded"):
            entry.as_json_fragment["state"] = state
            for callback in callbacks:
                callback("updated", entry)
        return {
            "flow_id": "change",
            "type": "abort",
            "reason": "reconfigure_successful",
        }

    manager.async_configure.side_effect = apply
    result = await engine.call(
        "ha_set_integration",
        arguments,
        CallContext("actor"),
    )
    assert len(captures) == 1
    assert captures[0]["kind"] == "integration"
    assert captures[0]["source_tool"] == "ha_set_integration"
    if during_backup != "unchanged":
        assert result.is_error, result.data
        assert result.data["error"]["code"] == (
            "CONFIG_CONFLICT" if during_backup == "revision" else "AUTH_REQUIRED"
        )
        manager.async_init.assert_not_awaited()
    else:
        assert not result.is_error, result.data
        assert result.data["status"] == "applied_and_verified"
        assert result.data["entry_state"] == "loaded"
        manager.async_init.assert_awaited_once_with(
            "demo", context={"source": "reconfigure", "entry_id": "entry"}
        )
        manager.async_configure.assert_awaited_once()
    assert not callbacks
    await engine.backend.stop()


@pytest.mark.parametrize("mode", ["create", "options"])
async def test_native_integration_create_and_options_share_existing_walkers(
    native: Any, flows: Any, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    backup = AsyncMock(return_value={"warnings": ["Backup warning"]})
    engine, _, manager, _, _ = _integration(native, monkeypatch, backup)
    manager.async_init.return_value = {
        "flow_id": "configure",
        "type": "form",
        "step_id": "user",
        "data_schema": [
            {"name": "host", "description": {"suggested_value": "192.0.2.2"}},
            {"name": "interval", "description": {"suggested_value": 10}},
        ],
    }
    manager.async_configure.return_value = {
        "flow_id": "configure",
        "type": "create_entry",
        "result": {"entry_id": "entry", "title": "Example"},
    }
    arguments = (
        {"domain": "demo", "config": {"host": "192.0.2.10", "interval": 30}}
        if mode == "create"
        else {"entry_id": "entry", "config": {"interval": 30}}
    )
    result = await engine.call("ha_set_integration", arguments, CallContext("actor"))
    assert not result.is_error, result.data
    assert manager.async_configure.await_args.args[1] == {
        "host": "192.0.2.10" if mode == "create" else "192.0.2.2",
        "interval": 30,
    }
    assert backup.await_count == (mode == "options")
    if mode == "options":
        assert "Backup warning" in result.data["warnings"]


async def test_upstream_knx_command_routes_to_the_existing_native_read_owner(
    native, flows, monkeypatch
):
    engine, entry, _manager, _callbacks, _user = _integration(
        native, monkeypatch, AsyncMock(return_value={})
    )
    entry.domain = "knx"
    entry.as_json_fragment["domain"] = "knx"
    schema_calls = []
    engine.backend.hass.data = {
        "websocket_api": {
            "knx/get_knx_project": (
                None,
                lambda message: schema_calls.append(message) or message,
            )
        }
    }
    read = AsyncMock(
        return_value={"success": True, "result": {"group_addresses": ["1/2/3"]}}
    )
    monkeypatch.setitem(
        native.DOMAIN_DIRECT_OPERATIONS, "integrations.knx_project", (read, False)
    )
    result = await engine.call(
        "ha_set_integration",
        {"entry_id": "entry", "ws_command": "knx/get_knx_project"},
        CallContext("actor"),
    )
    assert not result.is_error, result.data
    assert result.data["result"] == {"group_addresses": ["1/2/3"]}
    read.assert_awaited_once_with(engine.backend.hass, {})
    assert len(schema_calls) == 1
