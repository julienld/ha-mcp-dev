"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.flows.entry as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

_CreationFlowProgress = _shared._CreationFlowProgress
_MAX_REPLAY_STEPS = _shared._MAX_REPLAY_STEPS
_OptionsFlowProgress = _shared._OptionsFlowProgress
_RESTORE_REASON_MESSAGES = _shared._RESTORE_REASON_MESSAGES
_SAFE_RESTORE_FIELD_NAMES = _shared._SAFE_RESTORE_FIELD_NAMES
_SUBENTRY_CREATE_LOCKS = _shared._SUBENTRY_CREATE_LOCKS
_SUBMIT_TIMEOUT_S = _shared._SUBMIT_TIMEOUT_S
COMPONENT_DOMAIN = _shared.COMPONENT_DOMAIN
COMPONENT_ENTRY_SUGGESTIONS = _shared.COMPONENT_ENTRY_SUGGESTIONS
CreationFlowError = _shared.CreationFlowError
logger = _shared.logger
OptionsFlowError = _shared.OptionsFlowError
OptionsRestoreReason = _shared.OptionsRestoreReason
_cleanup_snapshot_creation = legacy_helper_flow(_shared._cleanup_snapshot_creation)
_created_subentry_id = legacy_helper_flow(_shared._created_subentry_id)
_creation_fields = legacy_helper_flow(_shared._creation_fields)
_json_differs = legacy_helper_flow(_shared._json_differs)
_menu_branch_from_snapshot = legacy_helper_flow(_shared._menu_branch_from_snapshot)
_reject_redaction_sentinels = legacy_helper_flow(_shared._reject_redaction_sentinels)
_restore_config_entry_options = legacy_helper_flow(
    _shared._restore_config_entry_options
)
_snapshot_answers = legacy_helper_flow(_shared._snapshot_answers)
_subentry_ids = legacy_helper_flow(_shared._subentry_ids)
_unknown_snapshot_fields = legacy_helper_flow(_shared._unknown_snapshot_fields)
config_entry_of_domain = legacy_helper_flow(_shared.config_entry_of_domain)
is_component_domain = legacy_helper_flow(_shared.is_component_domain)
recreate_flow_helper = legacy_helper_flow(_shared.recreate_flow_helper)
refuse_component_entry = legacy_helper_flow(_shared.refuse_component_entry)
replay_snapshot = legacy_helper_flow(_shared.replay_snapshot)
restore_config_entry_options = legacy_helper_flow(_shared.restore_config_entry_options)
subentry_create_lock = legacy_helper_flow(_shared.subentry_create_lock)

__all__ = [
    "_cleanup_snapshot_creation",
    "_created_subentry_id",
    "_creation_fields",
    "_CreationFlowProgress",
    "_json_differs",
    "_MAX_REPLAY_STEPS",
    "_menu_branch_from_snapshot",
    "_OptionsFlowProgress",
    "_reject_redaction_sentinels",
    "_restore_config_entry_options",
    "_RESTORE_REASON_MESSAGES",
    "_SAFE_RESTORE_FIELD_NAMES",
    "_snapshot_answers",
    "_SUBENTRY_CREATE_LOCKS",
    "_subentry_ids",
    "_SUBMIT_TIMEOUT_S",
    "_unknown_snapshot_fields",
    "COMPONENT_DOMAIN",
    "COMPONENT_ENTRY_SUGGESTIONS",
    "config_entry_of_domain",
    "CreationFlowError",
    "is_component_domain",
    "logger",
    "OptionsFlowError",
    "OptionsRestoreReason",
    "recreate_flow_helper",
    "refuse_component_entry",
    "replay_snapshot",
    "restore_config_entry_options",
    "subentry_create_lock",
]
