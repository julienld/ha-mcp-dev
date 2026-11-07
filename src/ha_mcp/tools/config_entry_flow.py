"""Legacy compatibility exports from ha_mcp.runtime.flows.entry."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime.flows import entry as _shared

OptionsFlowError = _shared.OptionsFlowError
CreationFlowError = _shared.CreationFlowError
_OptionsFlowProgress = _shared._OptionsFlowProgress
_json_differs = legacy_helper_flow(_shared._json_differs)
_unknown_snapshot_fields = legacy_helper_flow(_shared._unknown_snapshot_fields)
_CreationFlowProgress = _shared._CreationFlowProgress
_create_snapshot_helper = legacy_helper_flow(_shared._create_snapshot_helper)
_cleanup_snapshot_creation = legacy_helper_flow(_shared._cleanup_snapshot_creation)
_reject_redaction_sentinels = legacy_helper_flow(_shared._reject_redaction_sentinels)
_subentry_ids = legacy_helper_flow(_shared._subentry_ids)
_created_subentry_id = legacy_helper_flow(_shared._created_subentry_id)
set_config_subentry = legacy_helper_flow(_shared.set_config_subentry)
_run_config_subentry_flow = legacy_helper_flow(_shared._run_config_subentry_flow)
get_user_step_field_names = legacy_helper_flow(_shared.get_user_step_field_names)
update_config_entry_options = legacy_helper_flow(_shared.update_config_entry_options)
config_entry_of_domain = legacy_helper_flow(_shared.config_entry_of_domain)
is_component_domain = legacy_helper_flow(_shared.is_component_domain)
refuse_component_entry = legacy_helper_flow(_shared.refuse_component_entry)
_update_config_entry_options = legacy_helper_flow(_shared._update_config_entry_options)
update_flow_helper = legacy_helper_flow(_shared.update_flow_helper)
create_config_entry = legacy_helper_flow(_shared.create_config_entry)
create_flow_helper = legacy_helper_flow(_shared.create_flow_helper)
logger = _shared.logger
OptionsRestoreReason = _shared.OptionsRestoreReason
_RESTORE_REASON_MESSAGES = _shared._RESTORE_REASON_MESSAGES
_SAFE_RESTORE_FIELD_NAMES = _shared._SAFE_RESTORE_FIELD_NAMES
_SUBENTRY_CREATE_LOCKS = _shared._SUBENTRY_CREATE_LOCKS
COMPONENT_DOMAIN = _shared.COMPONENT_DOMAIN
COMPONENT_ENTRY_SUGGESTIONS = _shared.COMPONENT_ENTRY_SUGGESTIONS

__all__ = [
    "COMPONENT_DOMAIN",
    "COMPONENT_ENTRY_SUGGESTIONS",
    "CreationFlowError",
    "OptionsFlowError",
    "OptionsRestoreReason",
    "_CreationFlowProgress",
    "_OptionsFlowProgress",
    "_RESTORE_REASON_MESSAGES",
    "_SAFE_RESTORE_FIELD_NAMES",
    "_SUBENTRY_CREATE_LOCKS",
    "_cleanup_snapshot_creation",
    "_create_snapshot_helper",
    "_created_subentry_id",
    "_json_differs",
    "_reject_redaction_sentinels",
    "_run_config_subentry_flow",
    "_subentry_ids",
    "_unknown_snapshot_fields",
    "_update_config_entry_options",
    "config_entry_of_domain",
    "create_config_entry",
    "create_flow_helper",
    "get_user_step_field_names",
    "is_component_domain",
    "logger",
    "refuse_component_entry",
    "set_config_subentry",
    "update_config_entry_options",
    "update_flow_helper",
]
