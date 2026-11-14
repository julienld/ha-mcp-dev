"""Finite integration-management ports on the existing remote client."""

import json
from typing import Any

from ha_mcp.tool_api import ToolFailure, UnsupportedOperation
from ha_mcp.utils.config_hash import json_values_equal

from .remote_integration_reads import (
    INSPECTION_OPERATIONS,
    execute_inspection_operation,
)

INTEGRATION_OPERATIONS = frozenset(
    {
        *INSPECTION_OPERATIONS,
        "integrations.log_level.set",
        "integrations.enabled.set",
        "integrations.identity.entities",
        "integrations.identity.devices",
        "integrations.identity.unique_id",
        "config.entries.list",
        "integrations.commands",
        "integrations.command.execute",
    }
)


async def execute_integration_operation(
    client: Any, operation: str, arguments: dict[str, Any]
) -> Any:
    if operation in INSPECTION_OPERATIONS:
        return await execute_inspection_operation(client, operation, arguments)
    if operation == "integrations.identity.entities":
        from .remote_reconfigure_identity import _entry_entity_rows

        return await _entry_entity_rows(client, arguments["entry_id"])
    if operation == "integrations.identity.devices":
        from .remote_reconfigure_identity import _device_registry_rows

        return await _device_registry_rows(client, arguments["entry_id"])
    if operation == "integrations.identity.unique_id":
        from ha_mcp.tools.component_config_entries import fetch_config_entry_unique_id

        value = await fetch_config_entry_unique_id(client, arguments["entry_id"])
        return value._asdict()
    if operation in {
        "config.entries.list",
        "integrations.commands",
        "integrations.command.execute",
    }:
        return await _command_operation(client, operation, arguments)
    if operation == "integrations.log_level.set":
        return await client.send_websocket_message(
            {
                "type": "logger/integration_log_level",
                "integration": arguments["domain"],
                "level": arguments["level"],
                "persistence": arguments.get("persistence", "once"),
            }
        )
    if operation == "integrations.enabled.set":
        current = await client.get_config_entry(arguments["entry_id"])
        if not json_values_equal(current, arguments["expected_entry"]):
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "The integration changed after its snapshot was read; no enable/disable command was sent.",
                status="not_started",
            )
        return await client.send_websocket_message(
            {
                "type": "config_entries/disable",
                "entry_id": arguments["entry_id"],
                "disabled_by": None if arguments["enabled"] else "user",
            }
        )
    raise UnsupportedOperation(operation)


async def _command_operation(
    client: Any, operation: str, arguments: dict[str, Any]
) -> Any:
    from ha_mcp._vendor.fastmcp.exceptions import ToolError

    try:
        return await _execute_command(client, operation, arguments)
    except ToolError as error:
        payload = json.loads(str(error))
        failure = payload["error"]
        raise ToolFailure(failure["code"], failure["message"], data=payload) from error


async def _execute_command(
    client: Any, operation: str, arguments: dict[str, Any]
) -> Any:
    if operation == "config.entries.list":
        if not arguments:
            return await client.list_config_entries()
        return await client._request(
            "GET", "/config/config_entries/entry", params=arguments or None
        )
    if operation == "integrations.commands":
        from ha_mcp.tools.core_contract import integration_commands

        return await integration_commands(client, arguments["domain"])
    if operation == "integrations.command.execute":
        from ha_mcp.tools.backup_access import guard_snapshot_route

        message = arguments["message"]
        guard_snapshot_route(
            ws_command=message["type"],
            ws_params={k: v for k, v in message.items() if k != "type"},
        )
        return await client.send_websocket_message(arguments["message"])
    raise UnsupportedOperation(operation)
