"""Registered WS reads through the real reference consumer and validator.

HA state/services, decorators and transport are simulated explicitly. Registration,
Voluptuous schemas, component readers and server consumers are production code;
no Home Assistant instance, socket, listener or real credentials are used.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import voluptuous as _REAL_VOL

from ha_mcp.errors import HomeAssistantCommandError
from ha_mcp.tools import component_config_reads, reference_validator
from ha_mcp.tools.component_api import ComponentCaps

from .test_component_ws_search import (
    FakeHass,
    FakeServices,
    FakeState,
    FakeStates,
    _exceptions_stub,
    _FakeConnection,
    _FakeWSApi,
    _StubHomeAssistantError,
    wsapi,
)

_CONFIG = {
    "actions": [
        {
            "action": "light.turn_on",
            "target": {"entity_id": "light.kitchen"},
        }
    ]
}


@pytest.fixture
def reference_chain(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Connect the registered handler to the consumer at the simulated HA edge."""
    hass = FakeHass(
        states=[FakeState("light.kitchen")],
        services=FakeServices({"light": {"turn_on": {}}}),
    )
    fake_ws = _FakeWSApi()
    monkeypatch.setattr(wsapi, "websocket_api", fake_ws)
    monkeypatch.setattr(wsapi, "vol", _REAL_VOL)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", _exceptions_stub)
    wsapi.async_register_commands(hass)
    connection = _FakeConnection()

    def invoke(command: str = wsapi.WS_REFERENCE_DATA, **kwargs: Any) -> dict[str, Any]:
        handler = fake_ws.registered[command]
        params = _REAL_VOL.Schema(handler._ws_schema)({"type": command, **kwargs})
        handler(hass, connection, {**params, "id": 1})
        return connection.results[1]

    async def send(command_type: str, **kwargs: Any) -> dict[str, Any]:
        assert command_type in {
            wsapi.WS_REFERENCE_DATA,
            wsapi.config_references.WS_CONFIG_REFERENCES,
        }
        try:
            result = await asyncio.to_thread(invoke, command_type, **kwargs)
        except (RuntimeError, _StubHomeAssistantError) as exc:
            # Simulate HA's failed command crossing the WS client boundary.
            raise HomeAssistantCommandError(str(exc)) from exc
        return {"success": True, "result": result}

    transport = SimpleNamespace(send_command=AsyncMock(side_effect=send))
    monkeypatch.setattr(
        component_config_reads,
        "get_component_caps",
        AsyncMock(
            return_value=ComponentCaps(
                1, "2.2.3", frozenset({"reference_data", "config_references"}), {}
            )
        ),
    )
    monkeypatch.setattr(
        component_config_reads,
        "get_websocket_client",
        AsyncMock(return_value=transport),
    )
    from .test_component_ws_config_references import _fake_core

    monkeypatch.setattr(wsapi.config_references, "_core", _fake_core)
    hass.services.has_service = lambda domain, name: (
        name in hass.services.async_services().get(domain, {})
    )
    client = SimpleNamespace(
        base_url="http://offline.invalid",
        token="fake",
        get_states=AsyncMock(return_value=[{"entity_id": "light.kitchen"}]),
        get_services=AsyncMock(
            return_value=[{"domain": "light", "services": {"turn_on": {}}}]
        ),
    )
    return SimpleNamespace(
        hass=hass,
        invoke=invoke,
        connection=connection,
        client=client,
        transport=transport,
    )


def test_failed_enumeration_does_not_send_an_authoritative_empty_inventory(
    reference_chain: SimpleNamespace,
) -> None:
    failure = RuntimeError("state enumeration unavailable")
    reference_chain.hass.states.async_all = Mock(side_effect=failure)
    assert reference_chain.hass.states.get("light.kitchen") is not None

    with pytest.raises(RuntimeError) as caught:
        reference_chain.invoke()

    assert caught.value is failure
    assert not reference_chain.connection.results
    reference_chain.hass.states.async_all.assert_called_once_with()


async def test_core_verdict_traverses_registered_command_and_server_projection(
    reference_chain: SimpleNamespace,
) -> None:
    result = await reference_validator.validate_config_references(
        reference_chain.client, _CONFIG, "automation"
    )
    assert result == {"warnings": []}
    reference_chain.transport.send_command.assert_awaited_once_with(
        wsapi.config_references.WS_CONFIG_REFERENCES, kind="automation", config=_CONFIG
    )
    reference_chain.client.get_states.assert_not_awaited()
    reference_chain.client.get_services.assert_not_awaited()


async def test_empty_core_state_is_authoritative_without_a_catalog_fallback(
    reference_chain: SimpleNamespace,
) -> None:
    reference_chain.hass.states = FakeStates([])
    result = await reference_validator.validate_config_references(
        reference_chain.client, _CONFIG, "automation"
    )
    assert {(w["kind"], w["value"]) for w in result["warnings"]} == {
        ("entity", "light.kitchen")
    }
    reference_chain.client.get_states.assert_not_awaited()
    reference_chain.client.get_services.assert_not_awaited()


async def test_services_only_compatibility_read_never_enumerates_states(
    reference_chain: SimpleNamespace,
) -> None:
    reference_chain.hass.states.async_all = Mock(
        side_effect=RuntimeError("state enumeration unavailable")
    )
    result = await asyncio.to_thread(reference_chain.invoke, include_states=False)
    assert result == {
        "services": [{"domain": "light", "services": {"turn_on": {}}}],
        "entity_ids": [],
    }
    reference_chain.hass.states.async_all.assert_not_called()


@pytest.mark.parametrize("unavailable", ["states", "services"])
async def test_failed_core_check_reports_unchecked_without_copying_its_rules(
    reference_chain: SimpleNamespace, unavailable: str
) -> None:
    if unavailable == "states":
        reference_chain.hass.states.get = Mock(
            side_effect=RuntimeError("Core read failed")
        )
    else:
        reference_chain.hass.services.has_service = Mock(
            side_effect=RuntimeError("Core read failed")
        )
    result = await reference_validator.validate_config_references(
        reference_chain.client, _CONFIG, "automation"
    )
    assert result["warnings"] == []
    assert "RuntimeError" in result["references_unchecked"]
    reference_chain.client.get_states.assert_not_awaited()
    reference_chain.client.get_services.assert_not_awaited()


async def test_malformed_core_answer_does_not_become_an_authoritative_empty_result(
    reference_chain: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        wsapi.config_references,
        "async_config_references",
        AsyncMock(return_value={"status": "ok", "missing": None, "mismatches": []}),
    )
    result = await reference_validator.validate_config_references(
        reference_chain.client, _CONFIG, "automation"
    )
    assert result["warnings"] == []
    assert "malformed missing" in result["references_unchecked"]
    reference_chain.client.get_states.assert_not_awaited()
    reference_chain.client.get_services.assert_not_awaited()
