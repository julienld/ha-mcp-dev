"""Native YAML keeps actual Core validation, services, snapshots and actor gates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import async_mock_service

from custom_components.ha_mcp_tools.native_operations.yaml_config import NativeYamlConfig, NativeYamlRead
from ha_mcp.tool_api import ToolFailure

from ._native_file_core import core_files as core_files


@pytest.fixture
def yaml_files(core_files: SimpleNamespace):
    world = core_files
    return (
        NativeYamlConfig(world.manager, world.actor),
        NativeYamlRead(world.manager, world.actor),
        world.manager,
        world.config_file,
    )


@pytest.mark.parametrize("change", ["target", "key", "actor", "backup"])
async def test_native_yaml_change_during_safety_capture_never_rebases_or_writes(
    yaml_files, change
):
    edit, _read, manager, target = yaml_files
    manager.policy.flags.update(
        enable_yaml_edit_confirm=False, extra_yaml_write_keys="custom_domain"
    )
    target.write_text("custom_domain:\n  source: sensor.before\n")
    capture = manager.snapshots.file_backup
    captured = []

    async def capture_then_change(*args):
        await capture(*args)
        captured.append(True)
        if change == "target":
            target.write_text("custom_domain:\n  source: sensor.external\n")
        elif change == "key":
            manager.policy.flags["extra_yaml_write_keys"] = ""
        elif change == "actor":
            user = await manager.hass.auth.async_get_user(edit.actor.user_id)
            assert user is not None
            await manager.hass.auth.async_update_user(user, is_active=False)
        else:
            manager.policy.flags["enable_auto_backup"] = False

    manager.snapshots.file_backup = capture_then_change
    with pytest.raises(ToolFailure) as raised:
        await edit.edit(
            "custom_domain", "replace", "source: sensor.after\n", MandatoryBPS=False
        )
    assert captured == [True] and raised.value.status == "not_started"
    assert "sensor.after" not in target.read_text()


async def test_native_yaml_read_glob_uses_shared_lookup_and_never_resolves_secrets(
    yaml_files,
):
    _edit, read, _manager, target = yaml_files
    package = target.parent / "packages"
    package.mkdir()
    (package / "one.yaml").write_text("mqtt:\n  password: !secret mqtt_password\n")
    (package / "bad.yaml").write_text("mqtt: [unterminated\n")
    result = await read.get(
        yaml_path="mqtt", file="packages/*.yaml", include_parsed=True
    )
    assert result["files_searched"] == 2 and result["files_unreadable"] == 1
    assert result["matches"][0]["parsed"] == {"password": "!secret mqtt_password"}


@pytest.mark.parametrize(
    "error", ["plain component failure", {"code": "CONFIG_INVALID", "message": "nested failure"}]
)
def test_shared_error_preserves_string_and_structured_component_payloads(error):
    from ha_mcp.runtime.errors import raise_failure

    payload = {"success": False, "error": error}
    with pytest.raises(ToolFailure) as raised:
        raise_failure(payload)
    assert raised.value.data == payload
    assert raised.value.code == (error["code"] if isinstance(error, dict) else "TOOL_ERROR")
    assert str(raised.value) == (error["message"] if isinstance(error, dict) else error)


async def test_native_yaml_theme_reload_carries_the_actual_actor_context(
    hass: HomeAssistant, yaml_files,
):
    edit, _read, manager, _target = yaml_files
    manager.policy.flags["enable_yaml_edit_confirm"] = False
    calls = async_mock_service(hass, "frontend", "reload_themes")
    result = await edit.edit(
        "native-theme", "add", "primary-color: '#ffffff'\n",
        file="themes/native.yaml", MandatoryBPS=False,
    )
    assert result["post_action"] == "reload_performed" and result["written"]
    assert len(calls) == 1 and calls[0].context.user_id == edit.actor.user_id


@pytest.mark.parametrize("revoke", [False, True])
async def test_native_yaml_discovery_follows_nested_files_and_rechecks_authority(
    yaml_files, monkeypatch: pytest.MonkeyPatch, revoke: bool,
):
    from custom_components.ha_mcp_tools import yaml_find

    _edit, read, manager, target = yaml_files
    nested = target.parent / "packages" / "nested" / "child.yaml"
    nested.parent.mkdir(parents=True)
    nested.write_text("mqtt:\n  password: !secret mqtt_password\n")
    before = target.read_bytes(), nested.read_bytes()
    spy = AsyncMock(wraps=read.files.read_file)
    monkeypatch.setattr(read.files, "read_file", spy)

    async def discover(hass: HomeAssistant, yaml_path: str):
        assert hass is manager.hass and yaml_path == "mqtt"
        if revoke:
            user = await hass.auth.async_get_user(read.files.actor.user_id)
            assert user is not None
            await hass.auth.async_update_user(user, is_active=False)
        return ["packages/nested/child.yaml"]

    monkeypatch.setattr(yaml_find, "async_locate_yaml_key_files", discover)
    if revoke:
        with pytest.raises(ToolFailure):
            await read.get(yaml_path="mqtt", file="packages/*.yaml", include_parsed=True)
        assert spy.await_count == 0
    else:
        result = await read.get(yaml_path="mqtt", file="packages/*.yaml", include_parsed=True)
        assert result["files_searched"] == 1 and result["files_unreadable"] == 0
        assert result["matches"][0]["file"] == "packages/nested/child.yaml"
        assert result["matches"][0]["parsed"] == {"password": "!secret mqtt_password"}
    assert (target.read_bytes(), nested.read_bytes()) == before
    assert not manager.snapshot_store.list_snapshots(domain="yaml")
