"""Config entry metadata and helper-flow discovery from their Core owners."""

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant

from ha_mcp.errors import HomeAssistantAPIError


async def helper_types(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    from homeassistant.loader import async_get_config_flows

    return {"types": sorted(await async_get_config_flows(hass, type_filter="helper"))}


async def core_helper_types(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    from homeassistant.loader import async_get_integration_descriptions

    descriptions = await async_get_integration_descriptions(hass)
    return {"types": sorted(descriptions["core"]["helper"])}


async def entry_metadata(hass: HomeAssistant, arguments: dict[str, Any]) -> Any:
    entry = hass.config_entries.async_get_entry(arguments["entry_id"])
    if entry is None:
        raise HomeAssistantAPIError("Config entry not found", status_code=404)
    return entry.as_json_fragment


async def subentries(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    entry = hass.config_entries.async_get_entry(arguments["entry_id"])
    if entry is None:
        raise HomeAssistantAPIError("Config entry not found", status_code=404)
    return [
        {
            "subentry_id": row.subentry_id,
            "subentry_type": row.subentry_type,
            "title": row.title,
            "unique_id": row.unique_id,
        }
        for row in entry.subentries.values()
    ]


async def integration_commands(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    from ..core_contract import integration_commands as describe_commands

    result = describe_commands(hass, arguments)
    if any(
        row.get("command") != "knx/get_knx_project"
        for row in result.get("commands", [])
    ):
        result.setdefault("warnings", []).append(
            "These are Core's registered command schemas. Native dispatch currently ports knx/get_knx_project; other integration WS extensions require the Legacy runtime and refuse before dispatch here."
        )
    return result


async def flow_record(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    from ..flow_record import flow_record as read_record

    return read_record(hass, arguments)


async def component_capabilities(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    from ..websocket_api.constants import CAPABILITIES

    return {"capabilities": list(CAPABILITIES)}


async def flow_outline(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    from ..flow_outline import async_flow_outline

    return await async_flow_outline(hass, arguments)


DIRECT_OPERATIONS: dict[
    str, tuple[Callable[[HomeAssistant, dict[str, Any]], Awaitable[Any]], bool]
] = {
    "helpers.flow.types": (helper_types, False),
    "integrations.commands": (integration_commands, False),
    "helpers.flow.core_types": (core_helper_types, False),
    "config.entries.read": (entry_metadata, False),
    "config.flow.record": (flow_record, False),
    "config.flow.outline": (flow_outline, False),
    "component.capabilities": (component_capabilities, False),
    "config.subentries.list": (subentries, False),
}
