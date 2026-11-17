"""Shared remote label discovery preserves Core's complete registry rows."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import label_registry as lr
from homeassistant.setup import async_setup_component

from ha_mcp.backends.remote import RemoteBackend
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.runtime.labels import LabelDiscoveryTools
from ha_mcp.tool_api import CallContext


async def test_remote_label_discovery_survives_the_label_facade_migration(
    hass: HomeAssistant, core_client: HomeAssistantClient
) -> None:
    assert await async_setup_component(hass, "config", {})
    label = lr.async_get(hass).async_create("Kitchen", color="blue")
    expected = await core_client.send_websocket_message(
        {"type": "config/label_registry/list"}
    )
    assert expected["success"]
    tools = LabelDiscoveryTools(RemoteBackend(core_client), CallContext(None))

    result = await LabelDiscoveryTools.ha_config_get_label(tools)

    assert result["labels"] == expected["result"]
    assert any(row["label_id"] == label.label_id for row in result["labels"])
