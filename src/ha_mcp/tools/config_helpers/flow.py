"""Legacy exception facade for shared Core helper flow steps."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import helpers as _shared

_wait_for_flow_entities = legacy_helper_flow(_shared._wait_for_flow_entities)
_handle_flow_helper = legacy_helper_flow(_shared._handle_flow_helper)
_handle_set_config_subentry = legacy_helper_flow(_shared._handle_set_config_subentry)

__all__ = [
    "_handle_flow_helper",
    "_handle_set_config_subentry",
    "_wait_for_flow_entities",
]
