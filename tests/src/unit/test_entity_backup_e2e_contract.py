"""Entity history captures, restores and refusals use actual Core registry rows."""

import asyncio
import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from ha_mcp.backup_manager import BackupManager, get_backup_manager
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.config_settings import Settings
from ha_mcp.runtime.snapshot_payloads import BackupRestoreError


def history(
    client: HomeAssistantClient, directory: Path, *, enabled: bool = True
) -> BackupManager:
    return get_backup_manager(
        client,
        Settings(
            ENABLE_AUTO_BACKUP=enabled,
            HAMCP_BACKUP_DIR=str(directory),
            AUTO_BACKUP_THROTTLE_MINUTES=0,
        ),
    )


async def test_registry_backup_restores_actual_core_fields_and_uuid(
    hass: HomeAssistant, core_client: HomeAssistantClient, tmp_path: Path
) -> None:
    assert await async_setup_component(hass, "config", {})
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "sensor",
        "test",
        "backup",
        suggested_object_id="backup",
        original_name="Original",
    )
    entry = registry.async_update_entity(entry.entity_id, name="Saved")
    saved = json.loads(json.dumps(entry.extended_dict))
    manager = history(core_client, tmp_path)
    path = await manager.maybe_snapshot_known(
        "entity_registry", entry.id, saved, tool_name="ha_set_entity"
    )
    assert path is not None
    registry.async_update_entity(
        entry.entity_id,
        new_entity_id="sensor.renamed",
        name="Changed",
        hidden_by=er.RegistryEntryHider.USER,
    )
    result = await manager.restore_snapshot(path.name)
    restored = registry.async_get(entry.entity_id)
    assert restored is not None
    assert (
        restored.id == entry.id
        and restored.name == "Saved"
        and restored.hidden_by is None
    )
    assert registry.async_get("sensor.renamed") is None
    assert result["safety_backup"]


async def test_disabled_registry_capture_leaves_core_and_disk_unchanged(
    hass: HomeAssistant, core_client: HomeAssistantClient, tmp_path: Path
) -> None:
    assert await async_setup_component(hass, "config", {})
    registry = er.async_get(hass)
    entry = registry.async_get_or_create("sensor", "test", "no_capture")
    entry = registry.async_update_entity(entry.entity_id, name="Saved")
    saved = json.loads(json.dumps(entry.extended_dict))
    result = await history(core_client, tmp_path, enabled=False).maybe_snapshot_known(
        "entity_registry", entry.id, saved, tool_name="ha_set_entity"
    )
    assert result is None
    actual = registry.async_get(entry.entity_id)
    assert actual is not None
    assert json.loads(json.dumps(actual.extended_dict)) == saved
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob("*.yaml")))


async def test_deleted_registry_backup_without_component_explains_restart(
    hass: HomeAssistant, core_client: HomeAssistantClient, tmp_path: Path
) -> None:
    assert await async_setup_component(hass, "config", {})
    registry = er.async_get(hass)
    entry = registry.async_get_or_create("sensor", "test", "deleted")
    entry = registry.async_update_entity(entry.entity_id, name="Saved")
    saved = json.loads(json.dumps(entry.extended_dict))
    manager = history(core_client, tmp_path)
    path = await manager.maybe_snapshot_known(
        "entity_registry", entry.id, saved, tool_name="ha_set_entity"
    )
    assert path is not None
    registry.async_remove(entry.entity_id)
    with pytest.raises(BackupRestoreError) as caught:
        await manager.restore_snapshot(path.name)
    assert caught.value.outcome["reason"] == "entry_deleted"
    assert "Restart Home Assistant: if what provides" in json.dumps(
        caught.value.outcome
    )
    assert registry.async_get(entry.entity_id) is None


async def test_deleted_registry_backup_with_component_discloses_core_retention(
    hass: HomeAssistant, component_core_client: HomeAssistantClient, tmp_path: Path
) -> None:
    assert await async_setup_component(hass, "config", {})
    registry = er.async_get(hass)
    entry = registry.async_get_or_create("sensor", "test", "deleted_component")
    entry = registry.async_update_entity(entry.entity_id, name="Saved")
    saved = json.loads(json.dumps(entry.extended_dict))
    manager = history(component_core_client, tmp_path)
    path = await manager.maybe_snapshot_known(
        "entity_registry", entry.id, saved, tool_name="ha_set_entity"
    )
    assert path is not None
    registry.async_remove(entry.entity_id)
    with pytest.raises(BackupRestoreError) as caught:
        await manager.restore_snapshot(path.name)
    assert caught.value.outcome["reason"] == "entry_deleted"
    assert f"keeps the registry settings of {entry.entity_id} until " in json.dumps(
        caught.value.outcome
    )
    assert registry.async_get(entry.entity_id) is None
