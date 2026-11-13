"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.flows.form as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

MISSING = _shared.MISSING
_carries_sentinel = legacy_helper_flow(_shared._carries_sentinel)
form_submission = legacy_helper_flow(_shared.form_submission)
iter_schema_fields = legacy_helper_flow(_shared.iter_schema_fields)
shown_value = legacy_helper_flow(_shared.shown_value)

__all__ = [
    "_carries_sentinel",
    "form_submission",
    "iter_schema_fields",
    "MISSING",
    "shown_value",
]
