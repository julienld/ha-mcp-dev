"""Helper deletion uses the component's live Core registry lookup."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from ha_mcp import config
from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.tools.tools_integrations import IntegrationTools

from ._receipt_faults import on_receipt
from ._tool_errors import error_of

LOOKUP = "ha_mcp_tools/registry_lookup"


@pytest.fixture
def _core_helper_flows() -> None:
    """Use Core's installed helper integrations instead of the historical stand-in."""


@pytest.fixture
async def client(
    hass: HomeAssistant,
    component_core_client: HomeAssistantClient,
    monkeypatch: pytest.MonkeyPatch,
) -> HomeAssistantClient:
    assert await async_setup_component(hass, "config", {})
    monkeypatch.setattr(config.get_global_settings(), "enable_auto_backup", False)
    return component_core_client


async def test_flow_delete_finds_all_subentities_via_real_component(
    hass: HomeAssistant,
    client: HomeAssistantClient,
    entity_registry: er.EntityRegistry,
) -> None:
    entry = MockConfigEntry(domain="utility_meter", title="Energy")
    entry.add_to_hass(hass)
    members = {
        entity_registry.async_get_or_create(
            domain, "utility_meter", unique_id, config_entry=entry
        ).entity_id
        for domain, unique_id in [
            ("sensor", "peak"),
            ("sensor", "offpeak"),
            ("select", "tariff"),
        ]
    }
    other = MockConfigEntry(domain="light")
    other.add_to_hass(hass)
    noise = entity_registry.async_get_or_create(
        "light", "test", "other", config_entry=other
    )
    frames: list[dict[str, Any]] = []
    whole_lists: list[dict[str, Any]] = []
    with (
        on_receipt(hass, LOOKUP, lambda msg: frames.append(dict(msg))),
        on_receipt(
            hass,
            "config/entity_registry/list",
            lambda msg: whole_lists.append(dict(msg)),
        ),
    ):
        result = await IntegrationTools(client).ha_remove_helpers_integrations(
            target=sorted(
                entity_id for entity_id in members if entity_id.startswith("sensor.")
            )[0],
            helper_type="utility_meter",
            confirm=True,
            wait=False,
        )
    assert result["success"] is True
    assert result["entry_id"] == entry.entry_id
    assert set(result["entity_ids"]) == members
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert all(entity_registry.async_get(entity_id) is None for entity_id in members)
    assert entity_registry.async_get(noise.entity_id) is not None
    assert (
        len([msg for msg in frames if msg.get("config_entry_id") == entry.entry_id])
        == 1
    )
    assert whole_lists == []


async def _create_button(
    hass: HomeAssistant, client: HomeAssistantClient
) -> tuple[str, str]:
    assert await async_setup_component(hass, "input_button", {})
    created = await client.send_websocket_message(
        {"type": "input_button/create", "name": "My Button"}
    )
    await hass.async_block_till_done()
    storage_id = created["result"]["id"]
    entity_id = er.async_get(hass).async_get_entity_id(
        "input_button", "input_button", storage_id
    )
    assert entity_id is not None
    return storage_id, entity_id


async def test_simple_delete_resolves_in_one_component_lookup(
    hass: HomeAssistant,
    client: HomeAssistantClient,
    entity_registry: er.EntityRegistry,
) -> None:
    storage_id, entity_id = await _create_button(hass, client)
    lookups: list[dict[str, Any]] = []
    deletes: list[dict[str, Any]] = []
    with (
        on_receipt(hass, LOOKUP, lambda msg: lookups.append(dict(msg))),
        on_receipt(hass, "input_button/delete", lambda msg: deletes.append(dict(msg))),
    ):
        result = await IntegrationTools(client).ha_remove_helpers_integrations(
            target=entity_id, helper_type="input_button", confirm=True, wait=False
        )
    assert result["success"] is True
    assert result["unique_id"] == storage_id
    assert entity_registry.async_get(entity_id) is None
    assert len(deletes) == 1 and deletes[0]["input_button_id"] == storage_id
    assert len(lookups) == 1 and lookups[0]["entity_ids"] == [entity_id]


async def test_an_entity_the_component_misses_is_not_deleted_by_its_object_id(
    hass: HomeAssistant, client: HomeAssistantClient
) -> None:
    assert await async_setup_component(hass, "input_button", {})
    hass.states.async_set("input_button.my_button", "2026-01-01T00:00:00+00:00")
    deletes: list[dict[str, Any]] = []
    with (
        on_receipt(hass, "input_button/delete", lambda msg: deletes.append(dict(msg))),
        pytest.raises(ToolError) as error,
    ):
        await IntegrationTools(client).ha_remove_helpers_integrations(
            target="input_button.my_button",
            helper_type="input_button",
            confirm=True,
            wait=False,
        )
    assert error_of(error)["code"] == "RESOURCE_NOT_FOUND"
    assert deletes == []
