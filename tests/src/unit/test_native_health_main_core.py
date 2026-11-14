"""The Native public health facade exposes Main's actual Core data contract."""

from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import check_config
from homeassistant.setup import async_get_setup_timings, async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.health import NativeHealth
from ha_mcp.runtime.health_tools import HealthFacade
from ha_mcp.tool_api import CallContext

from ._native_core_backend import backend as backend


async def test_native_health_reports_core_config_errors_and_setup_timings(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    assert await async_setup_component(hass, "system_health", {})
    checked = await check_config.async_check_ha_config_file(hass)
    timings = dict(async_get_setup_timings(hass))
    service = NativeHealth(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    )

    result = await HealthFacade(service.get).ha_get_system_health(
        include="config_check,integration_startup,repairs"
    )

    assert result["success"] is True
    assert "type" not in result["health_info"]
    assert result["component_count"] == len(result["health_info"])
    assert result["config_check"] == {
        "result": "invalid" if checked.errors else "valid",
        "errors": checked.error_str or None,
        "warnings": checked.warning_str or None,
    }
    rows = result["integration_startup"]["integrations"]
    actual = {row["domain"]: row["seconds"] for row in rows}
    assert all(actual[domain] == seconds for domain, seconds in timings.items())
    assert [row["seconds"] for row in rows] == sorted(
        (row["seconds"] for row in rows), reverse=True
    )
    assert result["repairs"]["issues"] == []
