"""Legacy compatibility exports from ha_mcp.runtime.flows.submission."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import submission as _shared

FlowRef = _shared.FlowRef
_flow_texts = legacy_helper_flow(_shared._flow_texts)
ReconfigureStatus = _shared.ReconfigureStatus
_parse_flow_api_error = legacy_helper_flow(_shared._parse_flow_api_error)
_build_flow_error_context = legacy_helper_flow(_shared._build_flow_error_context)
_flow_error_subject = legacy_helper_flow(_shared._flow_error_subject)
_raise_flow_api_error = legacy_helper_flow(_shared._raise_flow_api_error)
_flow_failure_context = legacy_helper_flow(_shared._flow_failure_context)
redacted_step = legacy_helper_flow(_shared.redacted_step)
raise_form_errors = legacy_helper_flow(_shared.raise_form_errors)
abort_reason_text = legacy_helper_flow(_shared.abort_reason_text)
progress_action_text = legacy_helper_flow(_shared.progress_action_text)
raise_flow_abort = legacy_helper_flow(_shared.raise_flow_abort)
logger = _shared.logger

__all__ = [
    "FlowRef",
    "ReconfigureStatus",
    "_build_flow_error_context",
    "_flow_error_subject",
    "_flow_failure_context",
    "_flow_texts",
    "_parse_flow_api_error",
    "_raise_flow_api_error",
    "abort_reason_text",
    "logger",
    "progress_action_text",
    "raise_flow_abort",
    "raise_form_errors",
    "redacted_step",
]
