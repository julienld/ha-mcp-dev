"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.flows.submission as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

_FLOW_STILL_OPEN = _shared._FLOW_STILL_OPEN
FlowRef = _shared.FlowRef
logger = _shared.logger
ReconfigureStatus = _shared.ReconfigureStatus
_build_flow_error_context = legacy_helper_flow(_shared._build_flow_error_context)
_flow_failure_context = legacy_helper_flow(_shared._flow_failure_context)
_flow_texts = legacy_helper_flow(_shared._flow_texts)
_parse_flow_api_error = legacy_helper_flow(_shared._parse_flow_api_error)
_raise_flow_api_error = legacy_helper_flow(_shared._raise_flow_api_error)
abort_reason_text = legacy_helper_flow(_shared.abort_reason_text)
progress_action_text = legacy_helper_flow(_shared.progress_action_text)
raise_flow_abort = legacy_helper_flow(_shared.raise_flow_abort)
raise_form_errors = legacy_helper_flow(_shared.raise_form_errors)
redacted_step = legacy_helper_flow(_shared.redacted_step)

__all__ = [
    "_build_flow_error_context",
    "_flow_failure_context",
    "_FLOW_STILL_OPEN",
    "_flow_texts",
    "_parse_flow_api_error",
    "_raise_flow_api_error",
    "abort_reason_text",
    "FlowRef",
    "logger",
    "progress_action_text",
    "raise_flow_abort",
    "raise_form_errors",
    "ReconfigureStatus",
    "redacted_step",
]
