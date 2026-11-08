"""Remote flow admission and shutdown retain ownership across network waits."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ha_mcp.backends import remote_flow_ops
from ha_mcp.backends.remote import RemoteBackend
from ha_mcp.backends.remote_flow_ops import RemoteFlows
from ha_mcp.tool_api import CallContext, ToolFailure


async def test_stopped_backend_cannot_create_a_new_flow_owner():
    client = SimpleNamespace(
        start_config_flow=AsyncMock(return_value={"type": "form", "flow_id": "late"})
    )
    backend = RemoteBackend(client)
    await backend.stop()
    with pytest.raises(ToolFailure) as caught:
        await backend.execute(
            "config.flow.start", {"handler": "demo"}, CallContext("actor")
        )
    assert caught.value.status == "not_started"
    client.start_config_flow.assert_not_awaited()


async def test_concurrent_starts_reserve_the_configured_capacity(monkeypatch):
    monkeypatch.setattr(remote_flow_ops, "_MAX_FLOWS", 2, raising=False)
    entered, release = asyncio.Event(), asyncio.Event()
    issued = []

    async def start(_domain):
        flow_id = f"flow-{len(issued)}"
        issued.append(flow_id)
        if len(issued) >= 2:
            entered.set()
        await release.wait()
        return {"type": "form", "flow_id": flow_id}

    backend = RemoteFlows(
        SimpleNamespace(start_config_flow=AsyncMock(side_effect=start))
    )
    tasks = [
        asyncio.create_task(
            backend.execute(
                "config.flow.start", {"handler": "demo"}, CallContext("actor")
            )
        )
        for _ in range(3)
    ]
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        assert len(issued) == 2
        refused = [result for result in results if isinstance(result, ToolFailure)]
        assert len(refused) == 1 and refused[0].code == "FLOW_LIMIT"
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("operation", ["config.flow.start", "config.flow.read"])
async def test_shutdown_drains_admitted_flow_operations_before_cleanup(operation):
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(*_args):
        entered.set()
        await release.wait()
        return {"type": "form", "flow_id": "owned"}

    client = SimpleNamespace(
        start_config_flow=AsyncMock(side_effect=pending),
        _request=AsyncMock(side_effect=pending),
        abort_config_flow=AsyncMock(),
    )
    backend = RemoteFlows(client)
    actor = CallContext("actor")
    if operation == "config.flow.read":
        backend.owned["owned"] = ("config", actor.user_id, actor.client_id)
    task = asyncio.create_task(
        backend.execute(operation, {"handler": "demo", "flow_id": "owned"}, actor)
    )
    stop = None
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            stop = asyncio.create_task(backend.stop())
            await asyncio.sleep(0)
            assert not stop.done()
            release.set()
            await asyncio.gather(task, stop)
        assert not backend.owned
        client.abort_config_flow.assert_awaited_once_with("owned")
        with pytest.raises(ToolFailure) as caught:
            await backend.execute("config.flow.start", {"handler": "demo"}, actor)
        assert caught.value.status == "not_started"
    finally:
        release.set()
        await asyncio.gather(
            *(item for item in [task, stop] if item is not None), return_exceptions=True
        )


@pytest.mark.parametrize("operation", ["config.flow.start", "config.flow.abort"])
async def test_cancelled_flow_io_finishes_before_shutdown_without_abort_replay(
    operation,
):
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(*_args):
        entered.set()
        await release.wait()
        return {"type": "form", "flow_id": "owned"}

    client = SimpleNamespace(
        start_config_flow=AsyncMock(side_effect=pending),
        abort_config_flow=AsyncMock(side_effect=pending),
    )
    backend = RemoteFlows(client)
    actor = CallContext("actor")
    if operation == "config.flow.abort":
        backend.owned["owned"] = ("config", actor.user_id, actor.client_id)
    task = asyncio.create_task(
        backend.execute(operation, {"handler": "demo", "flow_id": "owned"}, actor)
    )
    stop = None
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            stop = asyncio.create_task(backend.stop())
            await asyncio.sleep(0)
            assert not stop.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            await stop
        assert not backend.owned
        client.abort_config_flow.assert_awaited_once_with("owned")
    finally:
        release.set()
        await asyncio.gather(
            *(item for item in [task, stop] if item is not None), return_exceptions=True
        )
