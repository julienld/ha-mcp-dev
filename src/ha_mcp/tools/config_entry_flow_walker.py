"""Legacy compatibility exports from ha_mcp.runtime.flows.walker."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import walker as _shared

flow_error_payload = legacy_helper_flow(_shared.flow_error_payload)
leaves_flow_open = legacy_helper_flow(_shared.leaves_flow_open)
_submit_step = legacy_helper_flow(_shared._submit_step)
_wait_for_progress = legacy_helper_flow(_shared._wait_for_progress)
_raise_no_answer = legacy_helper_flow(_shared._raise_no_answer)
_empty_forms_suggestions = legacy_helper_flow(_shared._empty_forms_suggestions)
_finish_flow_entry = legacy_helper_flow(_shared._finish_flow_entry)
_unconsumed_reconfigure_keys = legacy_helper_flow(_shared._unconsumed_reconfigure_keys)
_reconfigure_success_response = legacy_helper_flow(
    _shared._reconfigure_success_response
)
_reconfigure_abort_result = legacy_helper_flow(_shared._reconfigure_abort_result)
_handle_abort_step = legacy_helper_flow(_shared._handle_abort_step)
_rejected_on_submit = legacy_helper_flow(_shared._rejected_on_submit)
_flow_form_payload = legacy_helper_flow(_shared._flow_form_payload)
raise_reconfigure_created_entry = legacy_helper_flow(
    _shared.raise_reconfigure_created_entry
)
_handle_flow_create_entry = legacy_helper_flow(_shared._handle_flow_create_entry)
_wait_out_progress_or_refuse = legacy_helper_flow(_shared._wait_out_progress_or_refuse)
_handle_flow_steps = legacy_helper_flow(_shared._handle_flow_steps)
_handle_subentry_create_entry = legacy_helper_flow(
    _shared._handle_subentry_create_entry
)
_handle_subentry_abort = legacy_helper_flow(_shared._handle_subentry_abort)
_handle_config_subentry_flow_steps = legacy_helper_flow(
    _shared._handle_config_subentry_flow_steps
)
_RETRYABLE_GATEWAY_STATUS = _shared._RETRYABLE_GATEWAY_STATUS
logger = _shared.logger
EXTERNAL_STEP_TYPES = _shared.EXTERNAL_STEP_TYPES
_UNDRIVABLE_STEP_TYPES = _shared._UNDRIVABLE_STEP_TYPES
_RECONFIGURE_SUCCESS_REASONS = _shared._RECONFIGURE_SUCCESS_REASONS
POST_COMMIT_STATUSES = _shared.POST_COMMIT_STATUSES

_FlowType = _shared._FlowType
ReconfigureStatus = _shared.ReconfigureStatus
