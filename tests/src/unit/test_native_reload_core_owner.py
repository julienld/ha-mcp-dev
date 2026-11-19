"""Reload Native calls actual Core services, retaining actor and uncertain outcomes."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.system_actions import (
    NativeSystemActions,
)
from ha_mcp.runtime.system_actions import SystemActionsFacade
from ha_mcp.tool_api import CallContext, ToolFailure


@pytest.fixture
async def actions(hass: HomeAssistant, hass_admin_user: User) -> SystemActionsFacade:
    owner = NativeSystemActions(
        SimpleNamespace(hass=hass, backend=NativeBackend(hass)),
        CallContext(hass_admin_user.id),
    )
    return SystemActionsFacade(owner.restart, owner.reload)


async def test_loaded_domain_reload_keeps_the_actor(
    hass: HomeAssistant, hass_admin_user: User, actions: SystemActionsFacade
) -> None:
    calls: list[ServiceCall] = []

    async def reload(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("future_integration", "reload", reload)
    result = await actions.ha_reload_core(target="future_integration")
    assert result["service"] == "future_integration.reload"
    assert len(calls) == 1
    assert calls[0].context.user_id == hass_admin_user.id


async def test_all_delegates_the_sweep_to_core(
    hass: HomeAssistant, actions: SystemActionsFacade
) -> None:
    await hass.async_add_executor_job(
        Path(hass.config.config_dir, "configuration.yaml").write_text, ""
    )
    assert await async_setup_component(hass, "homeassistant", {})
    calls: list[ServiceCall] = []

    async def reload(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("future_integration", "reload", reload)
    hass.services.async_register("frontend", "reload_themes", reload)
    result = await actions.ha_reload_core()
    assert result["service"] == "homeassistant.reload_all"
    assert [call.domain for call in calls].count("future_integration") == 1


async def test_reload_failure_after_dispatch_is_unknown_and_not_replayed(
    hass: HomeAssistant, actions: SystemActionsFacade
) -> None:
    calls: list[ServiceCall] = []

    async def reload(call: ServiceCall) -> None:
        calls.append(call)
        raise HomeAssistantError("reload handler failed after it started")

    hass.services.async_register("future_integration", "reload", reload)
    with pytest.raises(ToolFailure) as failure:
        await actions.ha_reload_core(target="future_integration")
    assert len(calls) == 1
    assert failure.value.status == "outcome_unknown"


async def test_unregistered_plural_is_refused_before_dispatch(
    hass: HomeAssistant, actions: SystemActionsFacade
) -> None:
    async def reload(call: ServiceCall) -> None:
        pytest.fail("invalid target reached Core")

    hass.services.async_register("automation", "reload", reload)
    with pytest.raises(ToolFailure, match="Did you mean 'automation'"):
        await actions.ha_reload_core(target="automations")
