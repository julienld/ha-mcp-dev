"""Safety capture races are exercised against actual Core entries and actors."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_mcp_tools.const import DOMAIN
from custom_components.ha_mcp_tools.file_access import DATA_FILE_ACCESS
from ha_mcp.runtime.snapshot_payloads import BackupRestoreError
from ha_mcp.runtime.snapshot_store import SnapshotStore
from ha_mcp.tool_api import ToolFailure

from ._native_file_core import core_files as core_files


@pytest.mark.parametrize("change", ["target", "entry", "actor"])
async def test_native_file_restore_does_not_rebase_after_safety_capture(
    hass: HomeAssistant,
    core_files: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    world = core_files
    path = await hass.async_add_executor_job(
        world.store.capture,
        "yaml",
        "configuration.yaml::utility_meter",
        "restored: {}\n",
        "fixture",
    )
    entered, release = threading.Event(), threading.Event()
    original = SnapshotStore.capture
    captured: list[bool] = []

    def pause_capture(store, *args, **kwargs):
        result = original(store, *args, **kwargs)
        captured.append(True)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(SnapshotStore, "capture", pause_capture)
    task = asyncio.create_task(
        world.manager.snapshots.restore_snapshot(path.name, world.actor)
    )
    try:
        assert await hass.async_add_executor_job(entered.wait, 5)
        if change == "target":
            await hass.async_add_executor_job(
                world.config_file.write_text, "utility_meter:\n  external: {}\n"
            )
        elif change == "entry":
            hass.data[DOMAIN].pop(DATA_FILE_ACCESS)
        else:
            user = await hass.auth.async_get_user(world.actor.user_id)
            assert user is not None
            await hass.auth.async_update_user(user, is_active=False)
    finally:
        release.set()
    with pytest.raises(BackupRestoreError) as raised:
        await task
    assert captured == [True]
    assert raised.value.outcome["apply_status"] == "not_applied"
    assert "restored" not in world.config_file.read_text()


async def test_file_backup_target_cannot_read_unmasked_root_secrets(
    hass: HomeAssistant,
    core_files: SimpleNamespace,
) -> None:
    world = core_files
    await hass.async_add_executor_job(
        (world.config_file.parent / "secrets.yaml").write_text,
        "secret: do-not-disclose\n",
    )
    path = await hass.async_add_executor_job(
        world.store.capture, "file", "secrets.yaml", "saved", "fixture"
    )
    with pytest.raises(ToolFailure, match="not allowed"):
        await world.manager.snapshots.snapshot_comparison(path.name, world.actor)
