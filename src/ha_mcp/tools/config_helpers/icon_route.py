"""Legacy schema/read adapter for the shared icon policy."""

from typing import Any

from ha_mcp.errors import HomeAssistantError
from ha_mcp.runtime.helper_payload import icon_targets_from_schema
from ha_mcp.runtime.helper_payload import note_hidden_icon as _note_hidden_icon

from .. import component_helper_collections


async def icon_targets(
    client: Any, helper_type: str, action: str, icon: str | None
) -> tuple[str | None, str | None]:
    if icon is None:
        return None, None
    schemas = await component_helper_collections.fetch_helper_schemas(client)
    return icon_targets_from_schema(helper_type, action, icon, schemas)


async def note_hidden_icon(
    client: Any, entity_id: str | None, item_icon: str | None, warnings: list[str]
) -> None:
    """A failed advisory registry read never undoes the successful write."""
    if item_icon is None or not entity_id:
        return
    try:
        result = await client.send_websocket_message(
            {"type": "config/entity_registry/get", "entity_id": entity_id}
        )
    except (HomeAssistantError, OSError, TimeoutError):
        return
    entry = result.get("result") if result.get("success") else None
    override = entry.get("icon") if isinstance(entry, dict) else None
    _note_hidden_icon(entity_id, item_icon, override, warnings)
