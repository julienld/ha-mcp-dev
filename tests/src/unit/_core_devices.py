"""Devices created and owned by Core for remote and Native contract tests."""

from typing import Any
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)


def device(hass: HomeAssistant, domain: str, **kwargs: Any) -> dr.DeviceEntry:
    """A device in Core's registry, owned by a new config entry of ``domain``."""
    entry = MockConfigEntry(domain=domain)
    entry.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **kwargs
    )


async def removable_device(hass: HomeAssistant) -> dr.DeviceEntry:
    """A device of a set-up integration that lets Core remove its devices."""
    mock_integration(
        hass,
        MockModule(
            "removable",
            async_setup_entry=AsyncMock(return_value=None),
            async_remove_config_entry_device=AsyncMock(return_value=True),
        ),
    )
    mock_platform(hass, "removable.config_flow", None)
    dev = device(hass, "removable", identifiers={("removable", "1")})
    with mock_config_flow("removable", ConfigFlow):
        assert await hass.config_entries.async_setup(dev.config_entry_id)
    return dev
