"""A confirmed Core handler error does not erase a reload's possible side effects."""

import json

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.tools.tools_system import SystemTools


async def test_reload_error_after_effect_keeps_uncertainty_without_replay(
    hass: HomeAssistant,
    core_client: HomeAssistantClient,
) -> None:
    calls: list[ServiceCall] = []

    async def reload(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set("sensor.reload_effect", "after")
        raise HomeAssistantError("reload failed after changing state")

    hass.services.async_register("reload_probe", "reload", reload)
    with pytest.raises(ToolError) as caught:
        await SystemTools(core_client).ha_reload_core(target="reload_probe")
    assert len(calls) == 1
    state = hass.states.get("sensor.reload_effect")
    assert state is not None and state.state == "after"
    result = json.loads(str(caught.value))
    assert result["write_outcome_unknown"] is True
    assert result["execution_status"] == "outcome_unknown"
    assert "reload failed after changing state" in result["error"]["message"]
    assert result["ha_error_code"] == "home_assistant_error"
