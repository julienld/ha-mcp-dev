"""Legacy compatibility exports from ha_mcp.runtime.reconfigure_identity."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.backends.remote_reconfigure_identity import _registry_rows as _registry_rows
from ha_mcp.runtime import reconfigure_identity as _shared

EntryUniqueId = _shared.EntryUniqueId
fetch_config_entry_unique_id = legacy_helper_flow(_shared.fetch_config_entry_unique_id)
ReconfigureIdentity = _shared.ReconfigureIdentity
_normalise_identity_value = legacy_helper_flow(_shared._normalise_identity_value)
_is_hardware_identifier = legacy_helper_flow(_shared._is_hardware_identifier)
_device_hardware_ids = legacy_helper_flow(_shared._device_hardware_ids)
_entry_entity_rows = legacy_helper_flow(_shared._entry_entity_rows)
_device_registry_rows = legacy_helper_flow(_shared._device_registry_rows)
_collect_reconfigure_identity = legacy_helper_flow(
    _shared._collect_reconfigure_identity
)
RelatedEntries = _shared.RelatedEntries
cross_domain_warnings = legacy_helper_flow(_shared.cross_domain_warnings)
_classify_related_entries = legacy_helper_flow(_shared._classify_related_entries)
_validated_config_entry_rows = legacy_helper_flow(_shared._validated_config_entry_rows)
_has_reconfigure_identity_anchor = legacy_helper_flow(
    _shared._has_reconfigure_identity_anchor
)
_verification_state = legacy_helper_flow(_shared._verification_state)
_raise_identity_mismatch = legacy_helper_flow(_shared._raise_identity_mismatch)
check_reconfigure_identity = legacy_helper_flow(_shared.check_reconfigure_identity)
_check_identity_anchors = legacy_helper_flow(_shared._check_identity_anchors)
logger = _shared.logger
_KNOWN_AUXILIARY_ENTRY_DOMAINS = _shared._KNOWN_AUXILIARY_ENTRY_DOMAINS
_DEVICE_CONNECTION_ID_TYPES = _shared._DEVICE_CONNECTION_ID_TYPES
