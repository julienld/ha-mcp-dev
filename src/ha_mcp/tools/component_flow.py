"""Legacy component flow metadata facade over the shared runtime owner."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import component as _shared

flow_record = legacy_helper_flow(_shared.flow_record)
flow_outline = legacy_helper_flow(_shared.flow_outline)
steps_after = _shared.steps_after
