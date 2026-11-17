"""Scoped snapshot identities and affiliations are restored through real Core."""

from typing import cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import category_registry as cr
from homeassistant.helpers import floor_registry as fr

from ha_mcp.backup_diff import DiffResponse
from ha_mcp.backup_manager import BackupManager


async def test_deleted_category_scope_with_colon_is_preserved_in_restore_and_diff(
    hass: HomeAssistant, backup_manager: BackupManager
) -> None:
    registry = cr.async_get(hass)
    category = registry.async_create(scope="custom:scope", name="Saved")
    other = registry.async_create(scope="custom", name="Saved")
    identifier = f"custom:scope:{category.category_id}"
    path = await backup_manager.maybe_snapshot("category", identifier, force=True)
    assert path is not None
    registry.async_delete(scope="custom:scope", category_id=category.category_id)

    await backup_manager.restore_snapshot(path.name)
    restored = registry.async_list_categories(scope="custom:scope")
    assert len(restored) == 1 and restored[0].name == "Saved"
    assert restored[0].category_id != category.category_id
    untouched = registry.async_get_category(scope="custom", category_id=other.category_id)
    assert untouched is not None and untouched.name == "Saved"
    diff = cast(DiffResponse, await backup_manager.diff_snapshot(path.name))
    assert diff["entity_missing"] is False
    assert [(operation["path"], operation["value"]) for operation in diff["patch"]] == [
        ("/category_id", category.category_id)
    ]


async def test_area_restore_keeps_the_saved_floor_assignment(
    hass: HomeAssistant, backup_manager: BackupManager
) -> None:
    floors = fr.async_get(hass)
    saved_floor = floors.async_create("Saved floor")
    other_floor = floors.async_create("Other floor")
    areas = ar.async_get(hass)
    area = areas.async_create("Room", floor_id=saved_floor.floor_id)
    path = await backup_manager.maybe_snapshot("area_or_floor", f"area:{area.id}", force=True)
    assert path is not None
    areas.async_update(area.id, floor_id=other_floor.floor_id)

    await backup_manager.restore_snapshot(path.name)

    restored = areas.async_get_area(area.id)
    assert restored is not None
    assert restored.floor_id == saved_floor.floor_id