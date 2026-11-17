"""Development component builds keep PEP 440 ordering at service gates."""

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.tools import tools_filesystem
from ha_mcp.tools.util_helpers import unwrap_service_response

from ._file_services import make_file_service


@pytest.mark.parametrize("suffix", [".dev189467019982193", "b1", ""])
async def test_newer_component_build_can_call_file_services(
    hass: HomeAssistant,
    core_client: HomeAssistantClient,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    await make_file_service(hass)
    await hass.async_add_executor_job(Path(hass.config.path("www")).mkdir)
    integration = await async_get_integration(hass, "ha_mcp_tools")
    next_major = int(tools_filesystem.MIN_COMPONENT_VERSION.split(".")[0]) + 1
    monkeypatch.setitem(integration.manifest, "version", f"{next_major}.0.0{suffix}")

    result = await tools_filesystem.call_mcp_tools_service(
        core_client, "list_files", {"path": "www"}
    )

    assert unwrap_service_response(result)["success"] is True


async def test_development_build_of_required_stable_release_is_too_old(
    hass: HomeAssistant,
    core_client: HomeAssistantClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_file_service(hass)
    await hass.async_add_executor_job(Path(hass.config.path("www")).mkdir)
    integration = await async_get_integration(hass, "ha_mcp_tools")
    monkeypatch.setitem(
        integration.manifest,
        "version",
        f"{tools_filesystem.MIN_COMPONENT_VERSION}.dev1",
    )

    with pytest.raises(ToolError, match="too old"):
        await tools_filesystem.call_mcp_tools_service(
            core_client, "list_files", {"path": "www"}
        )
