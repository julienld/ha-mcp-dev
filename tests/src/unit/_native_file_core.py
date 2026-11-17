"""Native file owners bound to an actual Core entry, actor and service registry."""

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_mcp_tools.const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_TOOLS
from custom_components.ha_mcp_tools.file_access import DATA_FILE_ACCESS, FileAccess
from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_server_policy import NativePolicy
from custom_components.ha_mcp_tools.native_snapshots import NativeSnapshots
from ha_mcp.runtime.snapshot_store import SnapshotStore
from ha_mcp.tool_api import CallContext


@pytest.fixture
async def core_files(
    hass: HomeAssistant,
    hass_admin_user: User,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[SimpleNamespace]:
    for name in (
        "ENABLE_AUTO_BACKUP", "HAMCP_ENABLE_FILESYSTEM_TOOLS", "HAMCP_BACKUP_DIR",
        "ENABLE_BETA_FEATURES", "ENABLE_YAML_CONFIG_EDITING", "ENABLE_YAML_EDIT_CONFIRM",
        "ENABLE_MANDATORY_BPS",
    ):
        monkeypatch.delenv(name, raising=False)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_ENTRY_TYPE: ENTRY_TYPE_TOOLS})
    entry.add_to_hass(hass)
    owner = FileAccess(hass, entry=entry)
    hass.data.setdefault(DOMAIN, {})[DATA_FILE_ACCESS] = owner
    directory = Path(hass.config.config_dir)
    await hass.async_add_executor_job(lambda: (directory / "www").mkdir(exist_ok=True))
    await hass.async_add_executor_job((directory / "www" / "notes.txt").write_text, "before")
    await hass.async_add_executor_job((directory / "automations.yaml").write_text, "[]\n")
    config_file = directory / "configuration.yaml"
    await hass.async_add_executor_job(
        config_file.write_text,
        "# retained\nautomation: !include automations.yaml\nutility_meter:\n  original:\n    source: sensor.before\n",
    )
    history = tmp_path / "history"
    manager = SimpleNamespace(
        hass=hass,
        backend=NativeBackend(hass),
        policy=NativePolicy(flags={
            "enable_filesystem_tools": True, "enable_beta_features": True,
            "enable_auto_backup": True, "auto_backup_dir": str(history),
            "enable_yaml_config_editing": True, "enable_yaml_edit_confirm": True,
            "enable_mandatory_bps": False, "backup_read_only": False,
        }),
        settings_ui=SimpleNamespace(_io=hass.async_add_executor_job),
    )
    manager.snapshots = NativeSnapshots(manager)
    yield SimpleNamespace(
        manager=manager, actor=CallContext(hass_admin_user.id), owner=owner,
        config_file=config_file, store=SnapshotStore(history),
    )
    await manager.snapshots.async_stop()
    await owner.async_stop()
