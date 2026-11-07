"""Legacy compatibility exports from ha_mcp.runtime.flows.progress."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import progress as _shared

wait_for_progress = legacy_helper_flow(_shared.wait_for_progress)
PROGRESS_STEP_TYPES = _shared.PROGRESS_STEP_TYPES
PROGRESS_BUDGET_S = _shared.PROGRESS_BUDGET_S
POLL_INTERVAL_S = _shared.POLL_INTERVAL_S
_POLL_INTERVAL_MAX_S = _shared._POLL_INTERVAL_MAX_S
_FLOW_RESOURCES = _shared._FLOW_RESOURCES

__all__ = [
    "POLL_INTERVAL_S",
    "PROGRESS_BUDGET_S",
    "PROGRESS_STEP_TYPES",
    "_FLOW_RESOURCES",
    "_POLL_INTERVAL_MAX_S",
    "wait_for_progress",
]
