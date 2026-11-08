"""Observation cleanup cannot replace a committed reconfigure's outcome."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ha_mcp.runtime.reconfigure_watch import watch_entry_reload
from ha_mcp.tool_api import CallContext


@pytest.mark.parametrize("body_fails", [False, True])
async def test_failed_watch_close_preserves_the_reconfigure_outcome(body_fails):
    original = RuntimeError("reconfigure failure")

    async def execute(operation, _arguments, _context):
        if operation == "config.entries.close":
            raise OSError("watch close failed")
        if operation == "config.entries.observe":
            return {"state": "loaded"}
        return {"watch_id": "owned-watch"}

    client = SimpleNamespace(
        backend=SimpleNamespace(execute=AsyncMock(side_effect=execute)),
        context=CallContext("actor"),
    )

    async def reconfigure():
        async with watch_entry_reload(client, "entry") as settled:
            if body_fails:
                raise original
            return await settled()

    if body_fails:
        with pytest.raises(RuntimeError) as caught:
            await reconfigure()
        assert caught.value is original
    else:
        assert await reconfigure() == {"state": "loaded"}
    assert [call.args[0] for call in client.backend.execute.await_args_list].count(
        "config.entries.close"
    ) == 1


async def test_cancelled_watch_close_finishes_owned_io_before_propagating():
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def execute(operation, _arguments, _context):
        if operation == "config.entries.close":
            entered.set()
            await release.wait()
            finished.set()
        return {"watch_id": "owned-watch"}

    client = SimpleNamespace(
        backend=SimpleNamespace(execute=execute), context=CallContext("actor")
    )

    async def reconfigure():
        async with watch_entry_reload(client, "entry"):
            pass

    task = asyncio.create_task(reconfigure())
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not finished.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
