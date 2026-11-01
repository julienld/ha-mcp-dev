"""Abandoning a remote flow must release its bounded ownership slot."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ha_mcp.backends.remote_flow_ops import RemoteFlows
from ha_mcp.tool_api import CallContext, ToolFailure


@pytest.mark.parametrize(
    "error", [RuntimeError("abort failed"), asyncio.CancelledError()]
)
async def test_failed_or_cancelled_abort_releases_slot_without_replay(
    error: BaseException,
) -> None:
    abort = AsyncMock(side_effect=error)
    backend = RemoteFlows(SimpleNamespace(abort_config_flow=abort))
    backend.owned["flow"] = ("config", "actor", "client")
    actor = CallContext("actor", client_id="client")
    with pytest.raises(type(error)):
        await backend.execute("config.flow.abort", {"flow_id": "flow"}, actor)
    assert not backend.owned
    with pytest.raises(ToolFailure, match="does not own"):
        await backend.execute("config.flow.abort", {"flow_id": "flow"}, actor)
    abort.assert_awaited_once_with("flow")
