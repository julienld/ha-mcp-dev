"""Explicit Core preferences drive public search without default lookups."""

from typing import Any
from unittest.mock import Mock

import pytest
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools import core_assist
from ha_mcp.client.rest_client import HomeAssistantClient


async def test_explicit_overrides_avoid_default_reads(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    component_core_client: HomeAssistantClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    entry = entity_registry.async_get_or_create("light", "test", "override")
    hass.states.async_set(entry.entity_id, "on")
    expose_new = Mock(side_effect=AssertionError("must not be consulted"))
    default_exposed = Mock(side_effect=AssertionError("must not be consulted"))
    monkeypatch.setattr(core_assist, "_assist_expose_new_entities", expose_new)
    monkeypatch.setattr(core_assist, "_assist_default_exposed", default_exposed)
    original_get_settings = exposed_entities.async_get_entity_settings
    reads: list[tuple[str, dict[str, Any]]] = []

    def read_settings(home: HomeAssistant, entity_id: str) -> dict[str, Any]:
        settings = original_get_settings(home, entity_id)
        reads.append((entity_id, settings))
        return settings

    settings_read = Mock(wraps=read_settings)
    monkeypatch.setattr(exposed_entities, "async_get_entity_settings", settings_read)

    for should_expose in (True, False):
        reads.clear()
        settings_read.reset_mock()
        entity_registry.async_update_entity_options(
            entry.entity_id, "conversation", {"should_expose": should_expose}
        )
        response = await component_core_client.send_websocket_message(
            {
                "type": "ha_mcp_tools/search",
                "query": entry.entity_id,
                "search_types": ["entity"],
                "visibility": {"respect_assist_exposure": True},
            }
        )
        assert response["success"], response
        settings_read.assert_any_call(hass, entry.entity_id)
        explicit_reads = [
            settings for entity_id, settings in reads if entity_id == entry.entity_id
        ]
        assert explicit_reads
        assert all(
            settings["conversation"]["should_expose"] is should_expose
            for settings in explicit_reads
        )
        entities = {item["entity_id"] for item in response["result"]["entities"]}
        assert entities == ({entry.entity_id} if should_expose else set())
        expose_new.assert_not_called()
        default_exposed.assert_not_called()
