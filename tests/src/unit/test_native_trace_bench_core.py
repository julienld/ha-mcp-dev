"""The Native bench consumes the current trace API on Core's real store."""

from typing import Any

from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.traces import NativeTraces
from ha_mcp.runtime.trace_tools import TraceFacade
from ha_mcp.tool_api import CallContext
from tests.native.configuration_checks import exercise_traces

from ._trace_fixtures import script_run, store_runs


class TraceBench:
    """Repository-owned bench adapter forwarding every answer from Native Core."""

    def __init__(self, traces: NativeTraces) -> None:
        self.tools = TraceFacade(traces.get)
        self.completed: list[str] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "ha_get_automation_traces"
        return await self.tools.ha_get_automation_traces(**arguments)

    def passed(self, name: str) -> None:
        self.completed.append(name)


async def test_trace_bench_accepts_cores_extended_script_trace(
    hass: HomeAssistant, hass_admin_user: User
) -> None:
    assert await async_setup_component(hass, "trace", {})
    await store_runs(
        hass,
        script_run("bench-run", context_id="bench-context", item_id="native_contract"),
    )
    backend = NativeBackend(hass)
    checks = TraceBench(
        NativeTraces(hass, CallContext(hass_admin_user.id), authorize=backend.authorize)
    )
    await exercise_traces(checks)
    assert len(checks.completed) == 1
