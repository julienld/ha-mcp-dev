"""Legacy compatibility exports from ha_mcp.runtime.ignored_entries."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import ignored_entries as _shared

normalize_ignored_entry = legacy_helper_flow(_shared.normalize_ignored_entry)
refuse_ignored_entry = legacy_helper_flow(_shared.refuse_ignored_entry)
