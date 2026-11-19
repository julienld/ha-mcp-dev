"""Log and trace tools remain available through Core's actual Assist converter."""

from types import SimpleNamespace

import probatio
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from jsonschema import Draft202012Validator

from custom_components.ha_mcp_tools.llm_projection import convert_to_voluptuous
from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_log_tools import logs_definition
from custom_components.ha_mcp_tools.native_trace_tools import trace_definition
from ha_mcp._vendor.fastmcp import Client, FastMCP
from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp._vendor.fastmcp.tools.function_tool import FunctionTool
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.tool_api.llm_projection import normalise_schema
from ha_mcp.tools.tools_logs import LegacyLogsFacade, LogTools
from ha_mcp.tools.tools_traces import TraceTools, register_trace_tools

from ._trace_fixtures import script_run, store_runs


@pytest.mark.parametrize("adapter", ["native", "legacy"])
@pytest.mark.parametrize("tool_name", ["ha_get_automation_traces", "ha_get_logs"])
async def test_schema_survives_assist_conversion_and_core_reemission(
    hass: HomeAssistant, core_client: HomeAssistantClient, adapter: str, tool_name: str
) -> None:
    if adapter == "native":
        factory = (
            trace_definition
            if tool_name == "ha_get_automation_traces"
            else logs_definition
        )
        definition = factory(SimpleNamespace(hass=hass, backend=NativeBackend(hass)))
        schema = definition.input_schema
    else:
        owner = (
            TraceTools(core_client)
            if tool_name == "ha_get_automation_traces"
            else LegacyLogsFacade(LogTools(core_client).get_logs)
        )
        schema = FunctionTool.from_function(getattr(owner, tool_name)).parameters
    normalized = normalise_schema(schema, tool_name)
    parameters = convert_to_voluptuous(normalized)
    emitted = probatio.to_openapi(parameters)
    Draft202012Validator.check_schema(emitted)
    assert "ctx" not in schema.get("properties", {})
    validator = Draft202012Validator(emitted)
    assert validator.is_valid({"limit": 5})
    assert not validator.is_valid({"limit": "not-an-integer"})
    if tool_name == "ha_get_automation_traces":
        assert emitted["properties"]["offset"]["type"] == "integer"
    else:
        assert validator.is_valid({"hours_back": 1, "order": "oldest"})
        assert not validator.is_valid({"hours_back": "not-an-integer"})
        assert not validator.is_valid({"order": "invalid"})


async def test_trace_context_is_injected_and_emits_progress(
    hass: HomeAssistant, core_client: HomeAssistantClient
) -> None:
    assert await async_setup_component(hass, "trace", {})
    await store_runs(
        hass, script_run("schema-run", context_id="schema-context", item_id="uid_1")
    )
    server = FastMCP("trace context")
    register_trace_tools(server, core_client)
    progress_events: list[tuple[float, float | None, str | None]] = []

    async def progress(
        progress: float, total: float | None, message: str | None
    ) -> None:
        progress_events.append((progress, total, message))

    async with Client(server) as client:
        with pytest.raises(ToolError, match="Unexpected keyword"):
            await client.call_tool(
                "ha_get_automation_traces",
                {"domain": "script", "ctx": {"caller": "spoofed"}},
            )
        result = await client.call_tool(
            "ha_get_automation_traces",
            {"domain": "script", "item_id": "uid_1"},
            progress_handler=progress,
        )
    assert result.data["traces"][0]["run_id"] == "schema-run"
    assert [event[0] for event in progress_events] == [0, 1, 3]
    assert all(event[1] == 3 for event in progress_events)
