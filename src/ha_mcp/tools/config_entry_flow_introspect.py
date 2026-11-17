"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.flows.introspect as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

_ABORT_TIMEOUT_S = _shared._ABORT_TIMEOUT_S
_FlowType = _shared._FlowType
logger = _shared.logger
_flow_gone = legacy_helper_flow(_shared._flow_gone)
abort_failed_flow = legacy_helper_flow(_shared.abort_failed_flow)
abort_failed_flow_type_only = legacy_helper_flow(_shared.abort_failed_flow_type_only)
abort_probe_flow = legacy_helper_flow(_shared.abort_probe_flow)
menu_choices = legacy_helper_flow(_shared.menu_choices)
shielded_abort = legacy_helper_flow(_shared.shielded_abort)

__all__ = [
    "_ABORT_TIMEOUT_S",
    "_flow_gone",
    "_FlowType",
    "abort_failed_flow",
    "abort_failed_flow_type_only",
    "abort_probe_flow",
    "logger",
    "menu_choices",
    "shielded_abort",
]
