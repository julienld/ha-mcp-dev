"""Legacy errors over shared Core-driven helper descriptions."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import flow_description as _shared

MAX_OPTIONS = _shared.MAX_OPTIONS
compact_field = legacy_helper_flow(_shared.compact_field)
compact_schema = legacy_helper_flow(_shared.compact_schema)
describe_form = legacy_helper_flow(_shared.describe_form)
describe_helper = legacy_helper_flow(_shared.describe_helper)
describe_helper_response = legacy_helper_flow(_shared.describe_helper_response)
describe_step = legacy_helper_flow(_shared.describe_step)
refuse_menu_choice = legacy_helper_flow(_shared.refuse_menu_choice)
