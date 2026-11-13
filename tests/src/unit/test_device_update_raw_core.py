"""A device rename preserves Core's integration name and complete registry row."""

import json

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.json import json_bytes

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.devices import NativeDevices
from ha_mcp.tool_api import CallContext

from ._core_devices import device
from ._native_core_backend import backend as backend


@pytest.mark.parametrize("name", ["Den", ""])
async def test_native_device_rename_preserves_cores_original_name_and_full_row(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    name: str,
) -> None:
    target = device(
        hass, "hue", identifiers={("hue", "rename")}, name="Integration name"
    )
    registry = dr.async_get(hass)
    registry.async_update_device(target.id, name_by_user="Previous override")
    result = await NativeDevices(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    ).set(target.id, name=name)
    stored = registry.async_get(target.id)
    assert stored is not None
    assert stored.name == "Integration name"
    assert stored.name_by_user == (name or None)
    assert result["device_entry"] == json.loads(json_bytes(stored.dict_repr))
