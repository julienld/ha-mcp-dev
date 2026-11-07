"""Legacy compatibility exports from ha_mcp.runtime.flows.form."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import form as _shared
from ha_mcp.runtime.flows import schema as _schema

_extract_schema_field_names = legacy_helper_flow(_shared._extract_schema_field_names)
_consume_all_remaining_keys = legacy_helper_flow(_shared._consume_all_remaining_keys)
validate_step_values = legacy_helper_flow(_shared.validate_step_values)
_step_values_applied = legacy_helper_flow(_shared._step_values_applied)
_handle_form_step = legacy_helper_flow(_shared._handle_form_step)
__all__ = _shared.__all__
_MENU_SELECTION_KEYS = _schema._MENU_SELECTION_KEYS
_PER_STEP_VALUES_KEY = _schema._PER_STEP_VALUES_KEY
_RESERVED_CONFIG_KEYS = _schema._RESERVED_CONFIG_KEYS
_MISSING_DEFAULT = _schema._MISSING_DEFAULT
_NO_SUBMISSION = _schema._NO_SUBMISSION
iter_schema_fields = legacy_helper_flow(_schema.iter_schema_fields)
_section_path = legacy_helper_flow(_schema._section_path)
_ReuseState = _schema._ReuseState
_record_ignored_section_keys = legacy_helper_flow(_schema._record_ignored_section_keys)
_field_default_value = legacy_helper_flow(_schema._field_default_value)
_schema_default_values = legacy_helper_flow(_schema._schema_default_values)
_required_section_defaults = legacy_helper_flow(_schema._required_section_defaults)
_ignored_keys_warnings = legacy_helper_flow(_schema._ignored_keys_warnings)
_success_warnings = legacy_helper_flow(_schema._success_warnings)
_consume_section_schema = legacy_helper_flow(_schema._consume_section_schema)
_mark_consumed = legacy_helper_flow(_schema._mark_consumed)
_auto_confirm_form_payload = legacy_helper_flow(_schema._auto_confirm_form_payload)
_step_owned_submission_value = legacy_helper_flow(_schema._step_owned_submission_value)
_CLEARED = _schema._CLEARED
_strip_cleared = legacy_helper_flow(_schema._strip_cleared)
_is_redacted_value = legacy_helper_flow(_schema._is_redacted_value)
_current_value_backfill = legacy_helper_flow(_schema._current_value_backfill)
_clears_by_omission = legacy_helper_flow(_schema._clears_by_omission)
_edit_mode_submission = legacy_helper_flow(_schema._edit_mode_submission)
_redeclared_field_submission = legacy_helper_flow(_schema._redeclared_field_submission)
_consume_leaf_field = legacy_helper_flow(_schema._consume_leaf_field)
_consume_declared_section = legacy_helper_flow(_schema._consume_declared_section)
_consume_form_schema = legacy_helper_flow(_schema._consume_form_schema)
