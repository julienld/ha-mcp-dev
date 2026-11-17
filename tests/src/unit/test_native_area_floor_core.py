"""Native location edits use the running Core owners and schemas."""

from typing import Any, Literal

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import floor_registry as fr
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.runtime.area_writes import AreaWriteTools
from ha_mcp.tool_api import CallContext, ToolFailure


@pytest.fixture
async def locations(hass: HomeAssistant, hass_admin_user: User) -> AreaWriteTools:
    assert await async_setup_component(hass, "config", {})
    return AreaWriteTools(NativeBackend(hass), CallContext(hass_admin_user.id))


@pytest.mark.parametrize("kind", ["area", "floor"])
async def test_native_reorder_uses_core_and_returns_previous(
    hass: HomeAssistant, locations: AreaWriteTools, kind: Literal["area", "floor"]
) -> None:
    registry: Any = ar.async_get(hass) if kind == "area" else fr.async_get(hass)
    first = registry.async_create("First")
    second = registry.async_create("Second")
    previous = (
        [first.id, second.id] if kind == "area" else [first.floor_id, second.floor_id]
    )
    result = await locations.ha_set_area_or_floor(
        kind=kind, order=list(reversed(previous))
    )
    assert result["previous_order"] == previous
    assert result["order"] == list(reversed(previous))
    with pytest.raises(ToolFailure):
        await locations.ha_set_area_or_floor(kind=kind, order=previous[:1])
    assert result["order"] == [
        entry.id if kind == "area" else entry.floor_id
        for entry in getattr(registry, f"async_list_{kind}s")()
    ]


async def test_native_floor_omission_preserves_and_null_clears(
    hass: HomeAssistant, locations: AreaWriteTools
) -> None:
    registry = fr.async_get(hass)
    floor = registry.async_create("First", level=3)
    await locations.ha_set_area_or_floor(
        kind="floor", id=floor.floor_id, name="Renamed"
    )
    updated = registry.async_get_floor(floor.floor_id)
    assert updated is not None
    assert updated.level == 3
    await locations.ha_set_area_or_floor(kind="floor", id=floor.floor_id, level=None)
    cleared = registry.async_get_floor(floor.floor_id)
    assert cleared is not None
    assert cleared.level is None


@pytest.mark.parametrize("failure_type", [RuntimeError, ValueError])
@pytest.mark.parametrize("same_order", [False, True])
async def test_native_reorder_interruption_remains_unknown(
    hass: HomeAssistant,
    locations: AreaWriteTools,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[Exception],
    same_order: bool,
) -> None:
    registry = ar.async_get(hass)
    first = registry.async_create("First")
    second = registry.async_create("Second")
    calls = 0
    order = [first.id, second.id] if same_order else [second.id, first.id]

    def interrupted_save(self: ar.AreaRegistry) -> None:
        nonlocal calls
        calls += 1
        raise failure_type("save interrupted after reorder")

    with monkeypatch.context() as patched:
        patched.setattr(ar.AreaRegistry, "async_schedule_save", interrupted_save)
        with pytest.raises(ToolFailure) as failure:
            await locations.ha_set_area_or_floor(kind="area", order=order)
    assert failure.value.status == "outcome_unknown"
    assert failure.value.data["previous_order"] == [first.id, second.id]
    assert calls == 1
    assert [entry.id for entry in registry.async_list_areas()] == order
