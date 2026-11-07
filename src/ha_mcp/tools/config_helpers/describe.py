"""Legacy compatibility exports from ha_mcp.runtime.flow_description."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import flow_description as _shared

_option_values = legacy_helper_flow(_shared._option_values)
_compact_selector = legacy_helper_flow(_shared._compact_selector)
compact_field = legacy_helper_flow(_shared.compact_field)
compact_schema = legacy_helper_flow(_shared.compact_schema)
_with_static_hints = legacy_helper_flow(_shared._with_static_hints)
_with_help = legacy_helper_flow(_shared._with_help)
describe_form = legacy_helper_flow(_shared.describe_form)
_later_forms = legacy_helper_flow(_shared._later_forms)
refuse_menu_choice = legacy_helper_flow(_shared.refuse_menu_choice)
_progress_context = legacy_helper_flow(_shared._progress_context)
describe_step = legacy_helper_flow(_shared.describe_step)
_describe_flow = legacy_helper_flow(_shared._describe_flow)
_stored_item = legacy_helper_flow(_shared._stored_item)
_describe_simple = legacy_helper_flow(_shared._describe_simple)
describe_helper = legacy_helper_flow(_shared.describe_helper)
describe_helper_response = legacy_helper_flow(_shared.describe_helper_response)
MAX_OPTIONS = _shared.MAX_OPTIONS
_Submit = _shared._Submit
_SELECTOR_KEYS = _shared._SELECTOR_KEYS
_SERIALIZED_KEYS = _shared._SERIALIZED_KEYS
_LATER_FORM_TAIL = _shared._LATER_FORM_TAIL
_MORE_FORMS = _shared._MORE_FORMS

__all__ = [
    "MAX_OPTIONS",
    "_LATER_FORM_TAIL",
    "_MORE_FORMS",
    "_SELECTOR_KEYS",
    "_SERIALIZED_KEYS",
    "_Submit",
    "_compact_selector",
    "_describe_flow",
    "_describe_simple",
    "_later_forms",
    "_option_values",
    "_progress_context",
    "_stored_item",
    "_with_help",
    "_with_static_hints",
    "compact_field",
    "compact_schema",
    "describe_form",
    "describe_helper",
    "describe_helper_response",
    "describe_step",
    "refuse_menu_choice",
]
