"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.flows.submit as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

EXTERNAL_STEP_TYPES = _shared.EXTERNAL_STEP_TYPES
logger = _shared.logger
RECONFIGURE_SUCCESS_REASONS = _shared.RECONFIGURE_SUCCESS_REASONS
_raise_no_answer = legacy_helper_flow(_shared._raise_no_answer)
_rejected_on_submit = legacy_helper_flow(_shared._rejected_on_submit)
_submit_step = legacy_helper_flow(_shared._submit_step)
_wait_for_progress = legacy_helper_flow(_shared._wait_for_progress)
raise_reconfigure_created_entry = legacy_helper_flow(
    _shared.raise_reconfigure_created_entry
)

__all__ = [
    "_raise_no_answer",
    "_rejected_on_submit",
    "_submit_step",
    "_wait_for_progress",
    "EXTERNAL_STEP_TYPES",
    "logger",
    "raise_reconfigure_created_entry",
    "RECONFIGURE_SUCCESS_REASONS",
]
