"""Legacy compatibility exports from ha_mcp.runtime.flow_translations."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import flow_translations as _shared

strings_unread_warning = legacy_helper_flow(_shared.strings_unread_warning)
fetch_flow_strings = legacy_helper_flow(_shared.fetch_flow_strings)
field_help = legacy_helper_flow(_shared.field_help)
flow_text = legacy_helper_flow(_shared.flow_text)
logger = _shared.logger
_PLACEHOLDER = _shared._PLACEHOLDER
