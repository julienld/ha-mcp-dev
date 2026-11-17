"""Legacy errors over the shared helper call-shape rules."""

from ha_mcp.backends.legacy import legacy_errors_sync
from ha_mcp.runtime import helper_validation as _shared

_validate_set_helper_action = legacy_errors_sync(_shared._validate_set_helper_action)

__all__ = ["_validate_set_helper_action"]
