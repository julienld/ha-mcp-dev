"""Legacy errors over Core storage-helper payloads."""

from ha_mcp.backends.legacy import legacy_errors_sync
from ha_mcp.runtime import helper_payload as _shared

storage_fields = legacy_errors_sync(_shared.storage_fields)
with_create_defaults = legacy_errors_sync(_shared.with_create_defaults)
merged_update = legacy_errors_sync(_shared.merged_update)
