"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.integration_flow_steps as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

_FLOW_MANAGERS = _shared._FLOW_MANAGERS
_opened_flows = _shared._opened_flows
FlowTarget = _shared.FlowTarget
logger = _shared.logger
_finished_response = legacy_helper_flow(_shared._finished_response)
_form_payload = legacy_helper_flow(_shared._form_payload)
_menu_payload = legacy_helper_flow(_shared._menu_payload)
_raise_flow_not_open = legacy_helper_flow(_shared._raise_flow_not_open)
_record_anchor = legacy_helper_flow(_shared._record_anchor)
_refuse = legacy_helper_flow(_shared._refuse)
_require_flow_id = legacy_helper_flow(_shared._require_flow_id)
_require_opened = legacy_helper_flow(_shared._require_opened)
abort_open_flow = legacy_helper_flow(_shared.abort_open_flow)
abort_step_flow = legacy_helper_flow(_shared.abort_step_flow)
advance_flow = legacy_helper_flow(_shared.advance_flow)
drive_flow = legacy_helper_flow(_shared.drive_flow)
open_step_answer = legacy_helper_flow(_shared.open_step_answer)
options_target = legacy_helper_flow(_shared.options_target)
read_step = legacy_helper_flow(_shared.read_step)
run_integration_step = legacy_helper_flow(_shared.run_integration_step)
settle = legacy_helper_flow(_shared.settle)
start_setup_flow = legacy_helper_flow(_shared.start_setup_flow)
submit_step = legacy_helper_flow(_shared.submit_step)
unsent_answers_warning = legacy_helper_flow(_shared.unsent_answers_warning)

__all__ = [
    "_finished_response",
    "_FLOW_MANAGERS",
    "_form_payload",
    "_menu_payload",
    "_opened_flows",
    "_raise_flow_not_open",
    "_record_anchor",
    "_refuse",
    "_require_flow_id",
    "_require_opened",
    "abort_open_flow",
    "abort_step_flow",
    "advance_flow",
    "drive_flow",
    "FlowTarget",
    "logger",
    "open_step_answer",
    "options_target",
    "read_step",
    "run_integration_step",
    "settle",
    "start_setup_flow",
    "submit_step",
    "unsent_answers_warning",
]
