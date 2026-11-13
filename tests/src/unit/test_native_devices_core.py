"""Native device discovery and removal use Core owners and live admission."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.devices import NativeDevices
from ha_mcp.runtime.devices import DeviceDiscoveryTools
from ha_mcp.tool_api import CallContext, ToolFailure

from ._core_devices import device, removable_device
from ._native_core_backend import backend as backend


async def test_native_full_rows_keep_core_fields_and_owning_integration(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    dev = device(
        hass, "hue", identifiers={("different-id-namespace", "1")}, name="Lamp"
    )
    entity = er.async_get(hass).async_get_or_create(
        "light", "hue", "lamp", device_id=dev.id
    )
    tools = DeviceDiscoveryTools(backend, CallContext(hass_admin_user.id))
    result = await tools.ha_get_device(detail_level="full")
    row = result["devices"][0]
    expected = json.loads(json.dumps(dev.dict_repr))
    assert {key: row[key] for key in expected} == expected
    assert row["integration_type"] == "hue"
    assert row["entities"] == [json.loads(json.dumps(entity.as_partial_dict))]
    assert "integration_sources" not in row


async def test_native_linked_devices_are_cores_registry_links(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    mac = (dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")
    first = device(hass, "shelly", connections={mac})
    second = device(hass, "unifi", connections={mac})
    result = await DeviceDiscoveryTools(
        backend, CallContext(hass_admin_user.id)
    ).ha_get_device(device_id=first.id)
    assert result["device"]["linked_devices"] == [second.id]


async def test_native_removal_uses_core_command_after_recording_before_image(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    dev = await removable_device(hass)
    before = json.loads(json.dumps(dev.dict_repr))
    captured: list[dict[str, Any]] = []

    async def capture(snapshot: dict[str, Any], actor: CallContext) -> None:
        assert dr.async_get(hass).async_get(dev.id) is not None
        assert actor.user_id == hass_admin_user.id
        captured.append(snapshot)

    service = NativeDevices(
        hass,
        CallContext(hass_admin_user.id),
        authorize=backend.authorize,
        backup=capture,
    )
    result = await service.remove(dev.id)
    assert result["success"] is True
    assert result["message"] == "Device removed"
    assert dr.async_get(hass).async_get(dev.id) is None
    assert captured[0]["current_config"] == before


async def test_revocation_after_capture_prevents_core_device_dispatch(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    dev = await removable_device(hass)

    async def revoke(snapshot: dict[str, Any], actor: CallContext) -> None:
        hass_admin_user.is_active = False

    service = NativeDevices(
        hass,
        CallContext(hass_admin_user.id),
        authorize=backend.authorize,
        backup=revoke,
    )
    with pytest.raises(ToolFailure) as raised:
        await service.remove(dev.id)
    assert raised.value.code == "AUTH_FORBIDDEN"
    assert raised.value.status == "not_started"
    assert dr.async_get(hass).async_get(dev.id) is dev


async def test_read_only_admission_prevents_removal_and_backup(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    dev = await removable_device(hass)
    capture = AsyncMock()
    service = NativeDevices(
        hass,
        CallContext(hass_admin_user.id, read_only=True),
        authorize=backend.authorize,
        backup=capture,
    )
    with pytest.raises(ToolFailure) as raised:
        await service.remove(dev.id)
    assert raised.value.code == "READ_ONLY"
    capture.assert_not_awaited()
    assert dr.async_get(hass).async_get(dev.id) is dev


async def test_core_refusal_remains_visible_and_keeps_device(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    dev = device(hass, "hue", identifiers={("hue", "1")})
    service = NativeDevices(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    )
    with pytest.raises(ToolFailure) as raised:
        await service.remove(dev.id)
    assert raised.value.status == "not_started"
    assert dr.async_get(hass).async_get(dev.id) is dev
