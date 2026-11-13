"""Native diagnostics keep Core's complete artifact and unavailable-entry error."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_mcp_tools.const import DOMAIN, ENTRY_TYPE_TOOLS
from custom_components.ha_mcp_tools.native_operations.integration_inspection import (
    diagnostics,
)
from ha_mcp.errors import HomeAssistantAPIError


async def test_native_diagnostics_keeps_the_real_core_download_sections(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await async_setup_component(hass, "diagnostics", {})

    result = await diagnostics(hass, {"entry_id": entry.entry_id})

    assert result["integration_manifest"]["domain"] == DOMAIN
    assert "home_assistant" in result
    assert "issues" in result
    assert result["data"]["entries"][0]["entry_type"] == ENTRY_TYPE_TOOLS


async def test_native_diagnostics_refuses_a_missing_entry_without_a_partial_artifact(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, "diagnostics", {})
    with pytest.raises(HomeAssistantAPIError) as caught:
        await diagnostics(hass, {"entry_id": "no_such_entry"})
    assert caught.value.status_code == 404
