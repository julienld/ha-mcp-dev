"""A real Core-backed Native backend for configuration and device tests."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend


@pytest.fixture
async def backend(hass: HomeAssistant) -> NativeBackend:
    assert await async_setup_component(hass, "config", {})
    return NativeBackend(hass)
