"""Native registry operations reuse the existing owner/validator component seam."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant

from ha_mcp.tool_api import ToolFailure

from .core_entity_reads import enrich_entities, entity_exposure
from .core_registries import registry_snapshot
from .core_services import reference_data
from .native_operations.blueprints import render_blueprint
from .native_operations.config_reads import DIRECT_OPERATIONS as CONFIG_READ_OPERATIONS
from .optional_integrations import loaded_integration_module

# Existing shared-tool semantic names select Core readers directly. Transport
# adapters bind these same producers without participating in native execution.
CORE_READ_OPERATIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "registries.snapshot": registry_snapshot,
    "assist.exposure": entity_exposure,
    "entities.enrich": enrich_entities,
    "config.references.snapshot": reference_data,
}


def _require_loaded(hass: HomeAssistant, domain: str) -> None:
    if domain not in hass.config.components:
        raise ToolFailure("RADIO_UNAVAILABLE", f"{domain} integration is not loaded")


async def _zha_devices(hass: HomeAssistant, arguments: dict[str, Any]) -> Any:
    _require_loaded(hass, "zha")
    get_zha_gateway_proxy = loaded_integration_module(
        hass, "zha.helpers"
    ).get_zha_gateway_proxy

    gateway = get_zha_gateway_proxy(hass)
    return [device.zha_device_info for device in gateway.device_proxies.values()]


async def _zwave_node_status(hass: HomeAssistant, arguments: dict[str, Any]) -> Any:
    _require_loaded(hass, "zwave_js")
    node_status = loaded_integration_module(hass, "zwave_js.api").node_status
    async_get_node_from_device_id = loaded_integration_module(
        hass, "zwave_js.helpers"
    ).async_get_node_from_device_id

    try:
        node = async_get_node_from_device_id(hass, arguments["device_id"])
    except ValueError as error:
        raise ToolFailure("RADIO_UNAVAILABLE", str(error)) from error
    return node_status(node)


async def _matter_node_diagnostics(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> Any:
    _require_loaded(hass, "matter")
    matter_api = loaded_integration_module(hass, "matter.api")
    matter_helpers = loaded_integration_module(hass, "matter.helpers")
    MissingNode = matter_helpers.MissingNode
    get_matter = matter_helpers.get_matter
    node_from_ha_device_id = matter_helpers.node_from_ha_device_id

    try:
        matter = get_matter(hass)
        node = node_from_ha_device_id(hass, arguments["device_id"])
        if node is None:
            raise ToolFailure(
                "RADIO_UNAVAILABLE",
                f"Could not resolve Matter node from device id {arguments['device_id']}",
            )
        result = await matter.matter_client.node_diagnostics(node_id=node.node_id)
    except (
        matter_api.MatterError,
        MissingNode,
        matter_api.ServerVersionTooOld,
    ) as error:
        raise ToolFailure("RADIO_UNAVAILABLE", str(error)) from error
    return matter_api.dataclass_to_dict(result)


def _entity_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    from homeassistant.helpers import entity_registry as er

    return [entry.as_partial_dict for entry in er.async_get(hass).entities.values()]


async def _device_resolve(hass: HomeAssistant, arguments: dict[str, Any]) -> Any:
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers import entity_registry as er

    from .helper_collections import _INVALID_ERRORS

    try:
        entity_id = cv.entity_id(arguments["entity_id"])
    except _INVALID_ERRORS:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return entry.device_id if entry else None


async def _entity_list(hass: HomeAssistant, arguments: dict[str, Any]) -> Any:
    return _entity_rows(hass)


async def _entity_read(hass: HomeAssistant, arguments: dict[str, Any]) -> Any:
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers import entity_registry as er

    from .helper_collections import _INVALID_ERRORS

    registry = er.async_get(hass)
    ids = arguments["entity_ids"]
    entries: dict[str, Any] = {}
    errors: dict[str, str] = {}
    single = arguments.get("single", False)
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for raw in chunk:
            try:
                normalized = cv.entity_id(chunk[0] if single else raw)
            except _INVALID_ERRORS as error:
                errors[raw] = str(error)
                continue
            entry = registry.async_get(normalized)
            if entry is None:
                errors[raw] = "Entity not found"
            else:
                entries[raw] = entry.extended_dict
        await asyncio.sleep(0)
    return {"entries": entries, "errors": errors}


async def _device_single_snapshot(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> Any:
    from ha_mcp.runtime.device_records import _build_entity_maps
    from ha_mcp.utils.device_registry_semantics import (
        EFFECTIVE_AREA_MARKER,
        annotate_device_rows_with_effective_area,
    )

    from .core_device_reads import device_get, device_list

    device_id = arguments["device_id"]
    result = device_get(hass, device_id, include_entities=True)
    device, entities = result.get("device"), result.get("entities")
    if isinstance(device, dict) and isinstance(entities, list):
        device = dict(device)
        if "effective_area_id" in result:
            device[EFFECTIVE_AREA_MARKER] = result["effective_area_id"]
        devices = [device]
    else:
        devices = annotate_device_rows_with_effective_area(device_list(hass)["devices"])
        entities = _entity_rows(hass)
    _, entity_map = _build_entity_maps(entities, True)
    return {"devices": devices, "device_to_entities": entity_map}


async def _device_list_snapshot(hass: HomeAssistant, arguments: dict[str, Any]) -> Any:
    from ha_mcp.runtime.device_records import _build_entity_maps
    from ha_mcp.utils.device_registry_semantics import (
        annotate_device_rows_with_effective_area,
    )

    from .core_device_reads import device_list

    need_full = arguments["include_entities"]
    entities = _entity_rows(hass) if need_full else []
    _, entity_map = _build_entity_maps(entities, need_full)
    devices = annotate_device_rows_with_effective_area(device_list(hass)["devices"])
    return {"devices": devices, "device_to_entities": entity_map}


async def _device_linked(hass: HomeAssistant, arguments: dict[str, Any]) -> list[str]:
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    device_id = arguments["device_id"]
    device = registry.async_get(device_id)
    if device is None:
        raise ToolFailure(
            "RESOURCE_NOT_FOUND", "Device not found", status="not_started"
        )
    if isinstance(device, dr.ChildDeviceEntry):
        return []
    return [
        entry.id
        for entry in registry.async_get_devices(
            identifiers=device.identifiers, connections=device.connections
        )
        if entry.id != device_id
    ]


async def device_composite_splits(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    return {
        composite_id: {
            "split_ids": [device.id for device in devices],
            "primary_id": next(
                (
                    device.id
                    for device in devices
                    if device.config_entry_id == device.composite_primary_config_entry
                ),
                None,
            ),
        }
        for composite_id, devices in registry._devices.get_composite_splits().items()
    }


DIRECT_OPERATIONS: dict[
    str, Callable[[HomeAssistant, dict[str, Any]], Awaitable[Any]]
] = {
    "blueprints.render": render_blueprint,
    "radio.zha.devices": _zha_devices,
    "radio.zwave.node_status": _zwave_node_status,
    "radio.matter.node_diagnostics": _matter_node_diagnostics,
    "devices.resolve": _device_resolve,
    "devices.single_snapshot": _device_single_snapshot,
    "devices.linked": _device_linked,
    "devices.composite_splits": device_composite_splits,
    "devices.list_snapshot": _device_list_snapshot,
    "entities.registry.read": _entity_read,
    "entities.registry.list": _entity_list,
}

DIRECT_OPERATIONS.update(CONFIG_READ_OPERATIONS)
