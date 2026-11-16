"""Native state and group reads keep Core's repeated-report timestamp live."""

from datetime import datetime

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.groups import NativeGroups
from ha_mcp.runtime.group_tools import GroupTools
from ha_mcp.tool_api import CallContext

from ._native_test_engine import native_engine


@pytest.mark.parametrize("tool", ["ha_get_state", "ha_config_list_groups"])
async def test_native_reads_keep_a_repeated_report_visible(
    hass: HomeAssistant, hass_admin_user: User, tool: str
) -> None:
    entity_id = "group.repeated_report" if tool.endswith("groups") else "sensor.repeated_report"
    hass.states.async_set(entity_id, "0", timestamp=1_800_000_000.0)
    first = hass.states.get(entity_id)
    assert first is not None
    first.as_dict()
    hass.states.async_set(entity_id, "0", timestamp=1_800_000_060.0)
    current = hass.states.get(entity_id)
    assert current is not None
    expected = current.last_reported
    backend = NativeBackend(hass)
    actor = CallContext(hass_admin_user.id)
    if tool == "ha_get_state":
        result = await native_engine(backend, {tool}).call(
            tool, {"entity_id": entity_id}, actor
        )
        assert not result.is_error, result.data
        record = result.data["data"]
        assert "warnings" not in result.data
    else:
        owner = NativeGroups(hass, actor, authorize=backend.authorize)
        data = await GroupTools(owner).ha_config_list_groups()
        assert data["success"] is True
        record = data["groups"][0]
        assert "warnings" not in data
    assert datetime.fromisoformat(record["last_reported"]) == expected
