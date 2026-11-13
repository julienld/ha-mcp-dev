"""Native discovery retains actual Core registry rows and optional radio failures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.runtime import Engine
from ha_mcp.runtime.catalog import define_tool
from ha_mcp.runtime.devices import DeviceDiscoveryTools
from ha_mcp.runtime.entities import EntityDiscoveryTools
from ha_mcp.tool_api import CallContext, ToolFailure
from ha_mcp.tools.tool_hints import read_only_hints

from ._core_devices import device


async def test_native_device_lookup_keeps_disabled_entities_and_reports_missing_radio(
    hass: HomeAssistant,
    hass_admin_user: User,
) -> None:
    assert await async_setup_component(hass, "config", {})
    dev = device(hass, "zha", name="Probe", identifiers={("zha", "00:11")})
    entity = er.async_get(hass).async_get_or_create(
        "sensor",
        "zha",
        "probe",
        device_id=dev.id,
        original_name="Temperature",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    backend = NativeBackend(hass)
    definition = define_tool(
        backend,
        DeviceDiscoveryTools,
        "ha_get_device",
        annotations=read_only_hints("Get Device", open_world=False),
    )
    result = await Engine(backend, [definition]).call(
        "ha_get_device",
        {"entity_id": entity.entity_id},
        CallContext(hass_admin_user.id),
    )
    assert not result.is_error, result.data
    assert result.data["device"]["id"] == dev.id
    assert result.data["entities"][0]["disabled_by"] == "user"
    assert result.data["device"]["ieee_address"] == "00:11"
    assert result.data["warnings"]


async def test_native_bulk_entity_read_keeps_duplicate_order_and_extended_metadata(
    hass: HomeAssistant,
    hass_admin_user: User,
) -> None:
    registry = er.async_get(hass)
    dev = device(hass, "test", identifiers={("test", "1")}, name="Lamp")
    entry = registry.async_get_or_create(
        "light",
        "test",
        "stable",
        suggested_object_id="a",
        has_entity_name=True,
        device_id=dev.id,
    )
    entry = registry.async_update_entity(
        entry.entity_id, name="", aliases={"Desk"}, device_class="outlet"
    )
    registry.async_update_entity_options(
        entry.entity_id, "light", {"default_transition": 4}
    )
    backend = NativeBackend(hass)
    definition = define_tool(
        backend,
        EntityDiscoveryTools,
        "ha_get_entity",
        annotations=read_only_hints("Get Entity", open_world=False),
    )
    result = await Engine(backend, [definition]).call(
        "ha_get_entity",
        {"entity_id": [entry.entity_id, "light.missing", entry.entity_id]},
        CallContext(hass_admin_user.id),
    )
    assert not result.is_error, result.data
    assert [row["entity_id"] for row in result.data["entity_entries"]] == [
        entry.entity_id,
        entry.entity_id,
    ]
    row = result.data["entity_entries"][0]
    assert row["aliases"] == ["Desk"]
    assert row["device_class"] == "outlet" and row["uses_device_name"] is True
    assert row["options"] == {"light": {"default_transition": 4}}
    assert result.data["errors"] == [
        {"entity_id": "light.missing", "error": "Entity not found"}
    ]


@pytest.mark.parametrize(
    "refusal",
    [
        ToolFailure("AUTH_FORBIDDEN", "Credential revoked"),
        PermissionError("Credential revoked"),
    ],
)
async def test_optional_radio_cannot_soften_an_authorization_refusal(
    refusal: Exception,
) -> None:
    """A lost credential must fail the tool instead of returning earlier device data."""
    from ha_mcp.runtime.radio import enrich_zha_metrics

    backend = SimpleNamespace(execute=AsyncMock(side_effect=refusal))
    warnings: list[str] = []
    with pytest.raises(type(refusal), match="Credential revoked"):
        await enrich_zha_metrics(
            backend, CallContext("actor"), {"ieee_address": "00:11"}, warnings
        )
    assert not warnings
