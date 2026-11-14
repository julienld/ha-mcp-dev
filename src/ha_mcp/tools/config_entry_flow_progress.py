"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.flows.progress as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

_FLOW_RESOURCES = _shared._FLOW_RESOURCES
_POLL_INTERVAL_MAX_S = _shared._POLL_INTERVAL_MAX_S
POLL_INTERVAL_S = _shared.POLL_INTERVAL_S
PROGRESS_BUDGET_S = _shared.PROGRESS_BUDGET_S
PROGRESS_STEP_TYPES = _shared.PROGRESS_STEP_TYPES
wait_for_progress = legacy_helper_flow(_shared.wait_for_progress)

__all__ = [
    "_FLOW_RESOURCES",
    "_POLL_INTERVAL_MAX_S",
    "POLL_INTERVAL_S",
    "PROGRESS_BUDGET_S",
    "PROGRESS_STEP_TYPES",
    "wait_for_progress",
]
