"""Native integration backups restore options through a real Core flow."""

from types import SimpleNamespace

import pytest
from homeassistant.auth.models import User
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.runtime.snapshot_payloads import BackupRestoreError
from ha_mcp.tool_api import CallContext

from ._native_core_backend import backend as backend


@pytest.mark.parametrize("read_only", [False, True], ids=["restore", "read-only"])
async def test_native_options_restore_uses_core_and_preserves_write_admission(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    read_only: bool,
) -> None:
    from homeassistant.components.min_max.config_flow import (
        CONFIG_SCHEMA,
        OPTIONS_SCHEMA,
    )

    from custom_components.ha_mcp_tools.native_operations.integration_restore import (
        NativeIntegrationRestore,
    )

    hass.states.async_set("sensor.restore_first", "1")
    hass.states.async_set("sensor.restore_second", "2")
    created = await hass.config_entries.flow.async_init(
        "min_max",
        context={"source": "user"},
        data=CONFIG_SCHEMA(
            {
                "name": "Options restore",
                "entity_ids": ["sensor.restore_first", "sensor.restore_second"],
                "type": "min",
            }
        ),
    )
    assert created["type"] == FlowResultType.CREATE_ENTRY
    entry = created["result"]
    assert isinstance(entry, ConfigEntry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    snapshot = dict(entry.options)
    changed = {key: value for key, value in snapshot.items() if key != "name"}
    changed["type"] = "max"
    updated = await hass.config_entries.options.async_init(
        entry.entry_id, data=OPTIONS_SCHEMA(changed)
    )
    assert updated["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    current = dict(entry.options)
    assert current != snapshot

    config = {"entry_id": entry.entry_id, "domain": entry.domain, "options": snapshot}
    manager = SimpleNamespace(
        hass=hass, backend=backend, policy=SimpleNamespace(flag=lambda name: False)
    )
    owner = NativeIntegrationRestore(
        manager,
        CallContext(hass_admin_user.id, read_only=read_only),
        {"entity_id": entry.entry_id, "config": config},
    )
    before = await owner.current()
    assert before is not None
    if read_only:
        with pytest.raises(BackupRestoreError) as caught:
            await owner.restore_options(config, current)
        assert caught.value.outcome["apply_status"] == "not_applied"
        assert dict(entry.options) == current
    else:
        await owner.restore_options(config, current)
        assert dict(entry.options) == snapshot
    await hass.async_block_till_done()
