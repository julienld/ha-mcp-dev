"""Repository info follows the provider endpoint rather than the cache bridge."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ha_mcp.client.rest_client import HomeAssistantCommandError
from ha_mcp.tool_api import ToolFailure
from ha_mcp.tools.hacs_backend import StoreApi
from ha_mcp.tools.tools_hacs import HacsTools


@pytest.mark.parametrize("domain", ["hacs", "marketplace"])
@pytest.mark.parametrize("identifier", ["42", "Example/Repo"])
async def test_info_uses_the_store_refresh_endpoint(domain, identifier):
    async def send(command, **arguments):
        if command.endswith("/repositories/list"):
            return {
                "success": True,
                "result": [{"id": "42", "full_name": "example/repo"}],
            }
        assert command == f"{domain}/repository/info"
        assert arguments == {"repository_id": "42"}
        return {
            "success": True,
            "result": {"id": "42", "additional_info": "Fresh README", "future": True},
        }

    ws = SimpleNamespace(
        send_command=AsyncMock(side_effect=send),
        subscribe_command=AsyncMock(return_value=(1, asyncio.Queue())),
        unsubscribe_command=AsyncMock(),
    )
    client = MagicMock(get_config=AsyncMock(return_value={"time_zone": "UTC"}))
    tools = HacsTools(client)
    tools._get_hacs_client = AsyncMock(return_value=(ws, StoreApi(domain)))
    row = await tools._hacs_info(identifier)
    assert row["data"]["additional_info"] == "Fresh README"
    assert row["data"]["future"] is True
    assert all(
        call.args[0] != "ha_mcp_tools/hacs_cache"
        for call in ws.send_command.call_args_list
    )


async def test_info_failure_never_falls_back_or_replays():
    ws = SimpleNamespace(
        send_command=AsyncMock(
            side_effect=HomeAssistantCommandError("denied", "unauthorized")
        )
    )
    tools = HacsTools(MagicMock())
    tools._get_hacs_client = AsyncMock(return_value=(ws, StoreApi("hacs")))
    with pytest.raises(ToolFailure):
        await tools._hacs_info("42")
    ws.send_command.assert_awaited_once_with("hacs/repository/info", repository_id="42")
