"""Legacy imports for the shared reload observer."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from ha_mcp.backends.remote import RemoteBackend
from ha_mcp.runtime.entry_reload import (
    _TRANSIENT_RECONFIGURE_STATES as _TRANSIENT_RECONFIGURE_STATES,
)
from ha_mcp.runtime.entry_reload import (
    _entry_fragments as _entry_fragments,
)
from ha_mcp.runtime.entry_reload import (
    _is_transient_reconfigure_state as _is_transient_reconfigure_state,
)
from ha_mcp.runtime.entry_reload import (
    _observe_reload_settled as _observe_reload_settled,
)
from ha_mcp.runtime.flows.session import FlowSession
from ha_mcp.runtime.reconfigure_watch import watch_entry_reload as _watch_entry_reload
from ha_mcp.tool_api import CallContext


@asynccontextmanager
async def watch_entry_reload(
    client: Any, entry_id: str
) -> AsyncIterator[Callable[[], Awaitable[dict[str, Any] | None]]]:
    session = (
        client
        if isinstance(client, FlowSession)
        else FlowSession(RemoteBackend(client), CallContext(None))
    )
    async with _watch_entry_reload(session, entry_id) as settled:
        yield settled


__all__ = [
    "_TRANSIENT_RECONFIGURE_STATES",
    "_entry_fragments",
    "_is_transient_reconfigure_state",
    "_observe_reload_settled",
    "watch_entry_reload",
]
