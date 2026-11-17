"""Read a trace's logbook through the same Core processor as the frontend."""

import json
from typing import Any

from homeassistant.core import HomeAssistant

from ha_mcp.runtime.trace_logbook import TraceLogbook
from ha_mcp.utils.owned_executor import await_owned_io


async def trace_logbook(hass: HomeAssistant, trace: dict[str, Any]) -> TraceLogbook:
    context = trace.get("context") or {}
    context_id = context.get("id")
    start = (trace.get("timestamp") or {}).get("start")
    if not context_id:
        return TraceLogbook(
            [], None, ["No context id is available, so the trace logbook was not read."]
        )
    if not isinstance(start, str) or not start:
        return TraceLogbook(
            [],
            None,
            ["No trace start timestamp is available, so the logbook was not read."],
        )
    from homeassistant.components.recorder import get_instance
    from homeassistant.helpers.json import json_bytes

    from ..websocket_api.logbook import prepare_logbook_query

    query_start, query_end, processor = prepare_logbook_query(
        hass, start, None, None, None, str(context_id)
    )

    def read() -> list[dict[str, Any]]:
        return (
            json.loads(json_bytes(processor.get_events(query_start, query_end)))
            if processor
            else []
        )

    rows = await await_owned_io(get_instance(hass).async_add_executor_job(read))
    return TraceLogbook(rows[:50], "component", [], len(rows), len(rows) > 50)
