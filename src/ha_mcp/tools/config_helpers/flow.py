"""Legacy exception facade for shared Core helper flow steps."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import helpers as _shared

_flow_answers = legacy_helper_flow(_shared._flow_answers)
_append_unsent = legacy_helper_flow(_shared._append_unsent)
_wait_for_flow_entities = legacy_helper_flow(_shared._wait_for_flow_entities)
_apply_flow_registry_updates = legacy_helper_flow(_shared._apply_flow_registry_updates)
_handle_flow_helper = legacy_helper_flow(_shared._handle_flow_helper)
_subentry_action = legacy_helper_flow(_shared._subentry_action)
_handle_set_config_subentry = legacy_helper_flow(_shared._handle_set_config_subentry)
