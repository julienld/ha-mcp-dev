"""Legacy error translation for the shared entity field policies."""

from collections.abc import Awaitable, Callable
from typing import Any

from ha_mcp.backends.legacy import legacy_errors_sync
from ha_mcp.errors import create_entity_not_found_error
from ha_mcp.runtime import entity_fields as _fields

from .entity_registry_reads import NotInRegistry
from .helpers import raise_tool_error


async def ensure_use_device_name_allowed(
    use_device_name: bool | None,
    entity_id: str,
    fetch_entity: Callable[[str], Awaitable[dict[str, Any]]],
) -> dict[str, Any] | None:
    if not use_device_name:
        return None
    try:
        current = await fetch_entity(entity_id)
    except NotInRegistry:
        raise_tool_error(
            create_entity_not_found_error(
                entity_id, details=f"{entity_id} has no entity registry entry."
            )
        )
    reject_use_device_name_without_device(entity_id, current)
    return current


build_name_visibility_fields = legacy_errors_sync(_fields.build_name_visibility_fields)
build_state_tag_fields = legacy_errors_sync(_fields.build_state_tag_fields)
reject_name_with_use_device_name = legacy_errors_sync(
    _fields.reject_name_with_use_device_name
)
reject_use_device_name_without_device = legacy_errors_sync(
    _fields.reject_use_device_name_without_device
)
