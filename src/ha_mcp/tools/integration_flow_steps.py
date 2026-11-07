"""Legacy compatibility exports from ha_mcp.runtime.integration_flow_steps."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import integration_flow_steps as _shared

FlowTarget = _shared.FlowTarget
_raise_flow_not_open = legacy_helper_flow(_shared._raise_flow_not_open)
_require_opened = legacy_helper_flow(_shared._require_opened)
read_step = legacy_helper_flow(_shared.read_step)
_refuse = legacy_helper_flow(_shared._refuse)
_menu_payload = legacy_helper_flow(_shared._menu_payload)
_form_payload = legacy_helper_flow(_shared._form_payload)
submit_step = legacy_helper_flow(_shared.submit_step)
abort_step_flow = legacy_helper_flow(_shared.abort_step_flow)
settle = legacy_helper_flow(_shared.settle)
open_step_answer = legacy_helper_flow(_shared.open_step_answer)
_require_flow_id = legacy_helper_flow(_shared._require_flow_id)
_finished_response = legacy_helper_flow(_shared._finished_response)
drive_flow = legacy_helper_flow(_shared.drive_flow)
_start_setup_flow = legacy_helper_flow(_shared._start_setup_flow)
_options_target = legacy_helper_flow(_shared._options_target)
run_integration_step = legacy_helper_flow(_shared.run_integration_step)
logger = _shared.logger
_opened_flows = _shared._opened_flows

__all__ = [
    "FlowTarget",
    "_finished_response",
    "_form_payload",
    "_menu_payload",
    "_opened_flows",
    "_options_target",
    "_raise_flow_not_open",
    "_refuse",
    "_require_flow_id",
    "_require_opened",
    "_start_setup_flow",
    "abort_step_flow",
    "drive_flow",
    "logger",
    "open_step_answer",
    "read_step",
    "run_integration_step",
    "settle",
    "submit_step",
]
