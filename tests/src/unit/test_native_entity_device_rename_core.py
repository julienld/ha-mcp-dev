"""An entity's device rename is confirmed against the real Core registry."""

from typing import Any

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations import entity_writes
from custom_components.ha_mcp_tools.native_operations.entity_writes import (
    NativeEntityWrites,
)
from ha_mcp.tool_api import CallContext, ToolFailure

from ._native_core_backend import backend as backend


@pytest.mark.parametrize(
    ("child", "unexpected_change"),
    [(False, False), (True, False), (False, True)],
    ids=["main", "child", "unexpected-owner-change"],
)
async def test_entity_device_rename_confirms_only_the_expected_core_row(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    monkeypatch: pytest.MonkeyPatch,
    child: bool,
    unexpected_change: bool,
) -> None:
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    device: dr.DeviceEntry | dr.ChildDeviceEntry = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", "parent")},
        name="Original device",
    )
    if child:
        device = devices.async_get_or_create_child(
            config_entry_id=entry.entry_id,
            identifiers={("test", "child")},
            parent_device_id=device.id,
            name="Original child",
        )
    entity = er.async_get(hass).async_get_or_create(
        "sensor", "test", "power", device_id=device.id, original_name="Power"
    )
    captured: list[dict[str, Any]] = []

    async def capture(snapshot: dict[str, Any], actor: CallContext) -> None:
        assert actor.user_id == hass_admin_user.id
        captured.append(snapshot)

    dispatches = 0
    commit = entity_writes.commit_device_update

    def commit_with_unexpected_change(
        registry: dr.DeviceRegistry,
        current: dr.DeviceEntry | dr.ChildDeviceEntry,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal dispatches
        dispatches += 1
        result = commit(registry, current, payload)
        registry.async_update_device(current.id, manufacturer="Unexpected manufacturer")
        return result

    if unexpected_change:
        monkeypatch.setattr(
            entity_writes, "commit_device_update", commit_with_unexpected_change
        )

    service = NativeEntityWrites(
        hass,
        CallContext(hass_admin_user.id),
        authorize=backend.authorize,
        backup=capture,
    )
    if unexpected_change:
        with pytest.raises(ToolFailure) as caught:
            await service.set(entity.entity_id, new_device_name="Renamed device")
        assert caught.value.code == "OUTCOME_UNKNOWN"
        assert caught.value.status == "outcome_unknown"
        assert dispatches == 1
    else:
        result = await service.set(entity.entity_id, new_device_name="Renamed device")
        assert result["success"] is True

    updated = devices.async_get(device.id, include_composite_devices=False)
    assert updated is not None
    assert updated.name_by_user == "Renamed device"
    assert updated.identifiers == device.identifiers
    assert any(
        row["current_config"].get("id") == device.id
        and row["current_config"].get("name_by_user") is None
        for row in captured
    )
