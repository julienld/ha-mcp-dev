"""Existing remote transports behind finite integration-inspection ports."""

from typing import Any

from ha_mcp.tool_api import UnsupportedOperation

INSPECTION_OPERATIONS = frozenset(
    {
        "integrations.entries",
        "integrations.log_levels",
        "integrations.knx_project",
        "integrations.diagnostics",
    }
)


async def execute_inspection_operation(
    client: Any, operation: str, arguments: dict[str, Any]
) -> Any:
    if operation == "integrations.entries":
        from ha_mcp.tools.component_config_entries import fetch_config_entries

        result = await fetch_config_entries(client, **arguments)
        return (
            {
                "entries": result.rows,
                "secret_scrub_degraded": result.secret_scrub_degraded,
                "type_filtered": result.type_filtered,
            }
            if result is not None
            else None
        )
    if operation == "integrations.log_levels":
        return await client.send_websocket_message({"type": "logger/log_info"})
    if operation == "integrations.knx_project":
        return await client.send_websocket_message({"type": "knx/get_knx_project"})
    if operation == "integrations.diagnostics":
        endpoint = f"/diagnostics/config_entry/{arguments['entry_id']}"
        if arguments.get("device_id"):
            endpoint += f"/device/{arguments['device_id']}"
        return await client._request("GET", endpoint, timeout=arguments["timeout"])
    raise UnsupportedOperation(operation)
