"""Legacy compatibility exports from ha_mcp.runtime.flows.introspect."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import introspect as _shared

_flow_gone = legacy_helper_flow(_shared._flow_gone)
shielded_abort = legacy_helper_flow(_shared.shielded_abort)
abort_probe_flow = legacy_helper_flow(_shared.abort_probe_flow)
abort_failed_flow = legacy_helper_flow(_shared.abort_failed_flow)
abort_failed_flow_type_only = legacy_helper_flow(_shared.abort_failed_flow_type_only)
_FlowType = _shared._FlowType
_form_info = legacy_helper_flow(_shared._form_info)
_process_menu_flow_result = legacy_helper_flow(_shared._process_menu_flow_result)
menu_choices = legacy_helper_flow(_shared.menu_choices)
fetch_helper_flow_info = legacy_helper_flow(_shared.fetch_helper_flow_info)
logger = _shared.logger
_ABORT_TIMEOUT_S = _shared._ABORT_TIMEOUT_S
