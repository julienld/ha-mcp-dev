"""Registry semantic operations using the existing remote acquisition paths."""

from __future__ import annotations

from typing import Any

from ha_mcp.tool_api import ToolFailure, UnsupportedOperation

from .remote_config_finalize import CONFIG_FINALIZE_OPERATIONS, execute_config_finalize
from .remote_config_mutations import CONFIG_MUTATION_OPERATIONS, execute_config_mutation
from .remote_config_ops import CONFIG_READ_OPERATIONS, execute_config_operation
from .remote_registry_mutations import (
    REGISTRY_MUTATION_OPERATIONS,
    execute_registry_mutation,
)
from .remote_zone_ops import ZONE_OPERATIONS, execute_zone_operation

_FAMILY_OPERATIONS = {
    **dict.fromkeys(CONFIG_READ_OPERATIONS, execute_config_operation),
    **dict.fromkeys(CONFIG_MUTATION_OPERATIONS, execute_config_mutation),
    **dict.fromkeys(CONFIG_FINALIZE_OPERATIONS, execute_config_finalize),
    **dict.fromkeys(ZONE_OPERATIONS, execute_zone_operation),
    **dict.fromkeys(REGISTRY_MUTATION_OPERATIONS, execute_registry_mutation),
}

_RADIO_COMMANDS: dict[str, tuple[str, Any]] = {
    "radio.zha.devices": ("zha/devices", []),
    "radio.zwave.node_status": ("zwave_js/node_status", {}),
    "radio.matter.node_diagnostics": ("matter/node_diagnostics", {}),
}
REGISTRY_OPERATIONS = frozenset(
    {
        "registries.snapshot",
        "assist.exposure",
        "devices.resolve",
        "devices.single_snapshot",
        "devices.linked",
        "devices.entries",
        "devices.composite_splits",
        "devices.list_snapshot",
        "entities.registry.read",
        "entities.registry.list",
        "entities.enrich",
        "entities.discover",
        "entities.exposure.default",
        *_RADIO_COMMANDS,
        *CONFIG_READ_OPERATIONS,
        *CONFIG_MUTATION_OPERATIONS,
        *CONFIG_FINALIZE_OPERATIONS,
        *ZONE_OPERATIONS,
        *REGISTRY_MUTATION_OPERATIONS,
    }
)


async def _radio_read(client: Any, operation: str, arguments: dict[str, Any]) -> Any:
    from ha_mcp.client.rest_client import (
        HomeAssistantAPIError,
        HomeAssistantConnectionError,
    )

    command, default = _RADIO_COMMANDS[operation]
    try:
        result = await client.send_websocket_message({"type": command, **arguments})
    except (HomeAssistantAPIError, HomeAssistantConnectionError) as error:
        raise ToolFailure("RADIO_UNAVAILABLE", str(error)) from error
    if not result.get("success"):
        raise ToolFailure(
            "RADIO_UNAVAILABLE", str(result.get("error") or "request failed")
        )
    return result.get("result", default)


async def _device_read(client: Any, operation: str, arguments: dict[str, Any]) -> Any:
    if operation in {"devices.entries", "devices.composite_splits"}:
        from ha_mcp.tools.helpers import raise_core_refusal

        command, message = {
            "devices.entries": ("config_entries/get", "Failed to read config entries"),
            "devices.composite_splits": (
                "config/device_registry/list_composite_splits",
                "Failed to read composite device splits",
            ),
        }[operation]
        reply = await client.send_websocket_message({"type": command})
        if not reply.get("success"):
            raise_core_refusal(message, reply)
        return reply["result"]
    if operation == "devices.linked":
        from ha_mcp.tools.helpers import raise_core_refusal

        reply = await client.send_websocket_message(
            {
                "type": "config/device_registry/list_linked_devices",
                "device_id": arguments["device_id"],
            }
        )
        if not reply.get("success"):
            raise_core_refusal("Failed to read linked devices", reply)
        return reply["result"]["linked_devices"]
    from ha_mcp.tools import tools_registry as registry

    if operation == "devices.resolve":
        return await registry._resolve_device_id_for_entity(
            client, arguments["entity_id"]
        )
    if operation == "devices.single_snapshot":
        devices, entity_map = await registry._single_device_and_entities(
            client, arguments["device_id"]
        )
        return {"devices": devices, "device_to_entities": entity_map}
    need_full = arguments["include_entities"]
    entities = await registry._fetch_entity_rows(client) if need_full else []
    _, entity_map = registry._build_entity_maps(entities, need_full)
    devices = await registry._fetch_device_rows(client)
    return {"devices": devices, "device_to_entities": entity_map}


async def _entity_read(client: Any, operation: str, arguments: dict[str, Any]) -> Any:
    if operation == "entities.discover":
        from ha_mcp.tools.tools_entities import EntityTools

        return await EntityTools(client).ha_get_entity(**arguments)
    if operation == "entities.exposure.default":
        from ha_mcp.tools.entity_expose_batch import read_expose_new

        return await read_expose_new(client, arguments["assistant"])
    from ha_mcp.tools import tools_entities as entities

    if operation == "entities.registry.list":
        from ha_mcp.tools.helpers import raise_core_refusal

        reply = await client.send_websocket_message(
            {"type": "config/entity_registry/list"}
        )
        if not reply.get("success"):
            raise_core_refusal("Failed to read entity registry", reply)
        return reply.get("result") or []
    if operation == "entities.enrich":
        enrichment = await entities.fetch_entity_enrichment_via_component(
            client, arguments["entity_ids"]
        )
        return {"entities": enrichment} if enrichment is not None else None
    ids = arguments["entity_ids"]
    if not arguments.get("single"):
        from ha_mcp.tools.entity_registry_reads import get_entries_raw

        entries, errors = await get_entries_raw(client, ids)
        return {"entries": entries, "errors": errors}
    eid = ids[0]
    result = await client.send_websocket_message(
        {"type": "config/entity_registry/get", "entity_id": eid}
    )
    if result.get("success"):
        return {"entries": {eid: result.get("result") or {}}, "errors": {}}
    return {"entries": {}, "errors": {eid: entities._extract_ws_error(result)}}


async def execute_registry_operation(
    client: Any, operation: str, arguments: dict[str, Any]
) -> Any:
    """Keep capability negotiation and read-only fallbacks in the remote backend."""
    if operation in _FAMILY_OPERATIONS:
        return await _FAMILY_OPERATIONS[operation](client, operation, arguments)
    if operation in _RADIO_COMMANDS:
        return await _radio_read(client, operation, arguments)
    if operation in {
        "entities.registry.read",
        "entities.registry.list",
        "entities.enrich",
    }:
        return await _entity_read(client, operation, arguments)
    if operation in {
        "devices.resolve",
        "devices.single_snapshot",
        "devices.linked",
        "devices.entries",
        "devices.composite_splits",
        "devices.list_snapshot",
    }:
        return await _device_read(client, operation, arguments)
    if operation == "registries.snapshot" and arguments in (
        {"registries": ["area", "floor"]},
        {"registries": ["area"]},
    ):
        from ha_mcp.tools.tools_areas import AreaTools

        areas, floors = await AreaTools(client)._fetch_area_floor_registries({})
        rows = {"area": areas, "floor": floors}
        return {f"{name}s": rows[name] for name in arguments["registries"]}
    if operation == "registries.snapshot" and arguments == {"registries": ["label"]}:
        from ha_mcp.backends.legacy_labels import LegacyLabels

        return {"labels": await LegacyLabels(client)._list_labels()}
    if operation == "registries.snapshot" and arguments.get("registries") == [
        "category"
    ]:
        from ha_mcp.tools.tools_categories import CategoryTools

        scopes = arguments.get("category_scopes")
        if isinstance(scopes, list) and len(scopes) == 1 and isinstance(scopes[0], str):
            categories = await CategoryTools(client)._list_categories(scopes[0], None)
            return {"categories": {scopes[0]: categories}}
    if operation == "assist.exposure":
        from ha_mcp.tools.entity_exposure import read_exposure

        exposed, info, warning = await read_exposure(client)
        return {
            "exposed_entities": exposed,
            "entity_info": info,
            **({"warnings": [warning]} if warning else {}),
        }
    raise UnsupportedOperation(operation)
