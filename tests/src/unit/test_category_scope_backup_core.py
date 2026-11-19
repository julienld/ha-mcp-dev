"""Category snapshots preserve the complete Core scope across capture and restore."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import category_registry as cr

from ha_mcp.backup_manager import BackupManager


async def test_category_backup_restores_within_a_scope_containing_a_colon(
    hass: HomeAssistant, backup_manager: BackupManager
) -> None:
    registry = cr.async_get(hass)
    scope = "custom:scope"
    category = registry.async_create(scope=scope, name="Original", icon="mdi:star")
    other = registry.async_create(scope="custom", name="Unrelated")
    identifier = f"{scope}:{category.category_id}"

    snapshot = await backup_manager.maybe_snapshot("category", identifier, force=True)

    assert snapshot is not None
    registry.async_update(scope=scope, category_id=category.category_id, name="Changed")
    await backup_manager.restore_snapshot(snapshot.name)

    restored = registry.async_get_category(
        scope=scope, category_id=category.category_id
    )
    assert restored is not None
    assert (restored.name, restored.icon) == ("Original", "mdi:star")
    untouched = registry.async_get_category(
        scope="custom", category_id=other.category_id
    )
    assert untouched is not None
    assert untouched.name == "Unrelated"
