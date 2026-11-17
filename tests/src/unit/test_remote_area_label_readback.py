"""Shared remote area writes verify real Core label loss after dispatch."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import label_registry as lr
from homeassistant.setup import async_setup_component

from ha_mcp.backends.remote import RemoteBackend
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.runtime.area_writes import AreaWriteTools
from ha_mcp.tool_api import CallContext, ToolFailure

from ._client_spies import sent_commands
from ._command_faults import before_handling, pooled_socket


async def test_shared_remote_area_write_verifies_labels_removed_during_update(
    hass: HomeAssistant, core_client: HomeAssistantClient
) -> None:
    assert await async_setup_component(hass, "config", {})
    labels = lr.async_get(hass)
    label = labels.async_create("Guests")
    area = ar.async_get(hass).async_create("Kitchen")
    tools = AreaWriteTools(RemoteBackend(core_client), CallContext(None))

    with (
        before_handling(
            hass,
            "config/area_registry/update",
            lambda message: labels.async_delete(label.label_id),
        ),
        sent_commands(await pooled_socket(core_client)) as sent,
    ):
        with pytest.raises(ToolFailure) as failure:
            await tools.ha_set_area_or_floor(
                kind="area", id=area.id, labels=[label.label_id]
            )

    assert failure.value.data["write_committed"] is True
    assert failure.value.data["expected_labels"] == [label.label_id]
    types = [message["type"] for message in sent]
    assert "config/area_registry/list" in types[types.index("config/area_registry/update") + 1 :]
    stored = ar.async_get(hass).async_get_area(area.id)
    assert stored is not None and not stored.labels