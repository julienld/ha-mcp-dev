"""YAML confirmation and restore retain actual Core services and mandatory safety."""

from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_mcp_tools.native_operations.yaml_config import (
    NativeYamlConfig,
    NativeYamlRead,
)

from ._native_file_core import core_files as core_files


async def test_native_yaml_preview_then_confirm_captures_only_the_subtree(
    core_files: SimpleNamespace,
) -> None:
    world = core_files
    edit = NativeYamlConfig(world.manager, world.actor)
    before = world.config_file.read_text()
    preview = await edit.edit(
        "utility_meter",
        "replace",
        "requested:\n  source: sensor.after\n",
        MandatoryBPS=False,
    )
    assert preview["preview"] and world.config_file.read_text() == before
    assert world.store.list_snapshots(domain="yaml") == []
    saved = await edit.edit(
        "utility_meter",
        "replace",
        "requested:\n  source: sensor.after\n",
        confirm_token=preview["confirm_token"],
        MandatoryBPS=False,
    )
    assert saved["written"] and saved["config_check"] == "ok"
    assert saved["post_action"] == "restart_required"
    assert "# retained" in world.config_file.read_text()
    assert "!include automations.yaml" in world.config_file.read_text()
    rows = world.store.list_snapshots(domain="yaml")
    assert len(rows) == 1
    snapshot = world.store.read_snapshot(rows[0]["name"])
    assert snapshot["entity_id"] == "configuration.yaml::utility_meter"
    assert (
        "sensor.before" in snapshot["config"] and "!include" not in snapshot["config"]
    )
    read = await NativeYamlRead(world.manager, world.actor).get(
        yaml_path="utility_meter",
        include_parsed=True,
    )
    assert read["matches"][0]["parsed"] == {"requested": {"source": "sensor.after"}}


@pytest.mark.parametrize("domain", ["file", "yaml", "yaml_file"])
async def test_native_file_restore_keeps_safety_with_automatic_captures_disabled(
    hass: HomeAssistant,
    core_files: SimpleNamespace,
    domain: str,
) -> None:
    world = core_files
    world.manager.policy.flags["enable_auto_backup"] = False
    target = world.config_file
    identifier, saved = (
        "configuration.yaml",
        "utility_meter:\n  restored:\n    source: sensor.saved\n",
    )
    if domain == "file":
        target = target.parent / "www" / "notes.txt"
        identifier, saved = "www/notes.txt", "saved plain text"
    elif domain == "yaml":
        identifier, saved = (
            identifier + "::utility_meter",
            "restored:\n  source: sensor.saved\n",
        )
    path = await hass.async_add_executor_job(
        world.store.capture, domain, identifier, saved, "fixture"
    )
    data, before = await world.manager.snapshots.snapshot_comparison(
        path.name, world.actor
    )
    assert data["config"] == saved and before is not None
    restored = await world.manager.snapshots.restore_snapshot(path.name, world.actor)
    assert restored["apply_status"] == "applied" and restored["safety_backup"]
    assert world.store.read_snapshot(restored["safety_backup"])["config"] == before
    assert "saved" in target.read_text()
    assert len(world.store.list_snapshots(domain=domain)) == 2

@pytest.mark.parametrize("gap", ["", "\n"], ids=["directly-above", "blank-line-between"])
async def test_native_remove_preserves_the_next_sections_comments(
    hass: HomeAssistant, core_files: SimpleNamespace, gap: str
) -> None:
    world = core_files
    head = "automation: !include automations.yaml\n\n"
    removed = "utility_meter:\n  original:\n    source: sensor.before\n\n"
    tail = "# Phone notifications\n# Set up by hand\n" + gap + "notify: []\n"
    await hass.async_add_executor_job(world.config_file.write_text, head + removed + tail)
    edit = NativeYamlConfig(world.manager, world.actor)
    preview = await edit.edit("utility_meter", "remove", MandatoryBPS=False)
    assert world.config_file.read_text() == head + removed + tail
    result = await edit.edit(
        "utility_meter", "remove", confirm_token=preview["confirm_token"], MandatoryBPS=False
    )
    assert result["written"] is True
    assert world.config_file.read_text() == head + tail
