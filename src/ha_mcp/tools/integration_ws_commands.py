"""Legacy compatibility exports from ha_mcp.runtime.integration_ws_commands."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import integration_ws_commands as _shared

reject_ws_command_conflicts = legacy_helper_flow(_shared.reject_ws_command_conflicts)
attach_ws_commands = legacy_helper_flow(_shared.attach_ws_commands)
_list_commands = legacy_helper_flow(_shared._list_commands)
send_ws_command = legacy_helper_flow(_shared.send_ws_command)
logger = _shared.logger
_LIST_SUGGESTION = _shared._LIST_SUGGESTION
