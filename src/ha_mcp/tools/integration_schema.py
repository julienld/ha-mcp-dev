"""Legacy compatibility exports from ha_mcp.runtime.integration_schema."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import integration_schema as _shared

options_from_form_flow = legacy_helper_flow(_shared.options_from_form_flow)
withhold_component_options = legacy_helper_flow(_shared.withhold_component_options)
redact_options_by_form = legacy_helper_flow(_shared.redact_options_by_form)
entry_count = legacy_helper_flow(_shared.entry_count)
options_unread_warning = legacy_helper_flow(_shared.options_unread_warning)
options_withheld_warning = legacy_helper_flow(_shared.options_withheld_warning)
_entry_domain = legacy_helper_flow(_shared._entry_domain)
_put_payload = legacy_helper_flow(_shared._put_payload)
fetch_options_schema = legacy_helper_flow(_shared.fetch_options_schema)
fetch_config_subentry_schema = legacy_helper_flow(_shared.fetch_config_subentry_schema)
describe_flow_form = legacy_helper_flow(_shared.describe_flow_form)
logger = _shared.logger
_MENU_NOTE = _shared._MENU_NOTE

__all__ = [
    "_MENU_NOTE",
    "_entry_domain",
    "_put_payload",
    "describe_flow_form",
    "entry_count",
    "fetch_config_subentry_schema",
    "fetch_options_schema",
    "logger",
    "options_from_form_flow",
    "options_unread_warning",
    "options_withheld_warning",
    "redact_options_by_form",
    "withhold_component_options",
]
