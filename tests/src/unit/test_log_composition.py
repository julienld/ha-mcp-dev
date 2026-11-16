"""Regressions at the upstream record/native shared-contract boundary."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.runtime.error_log_journald import JournaldPage, journald_page
from ha_mcp.runtime.log_tools import LogsFacade
from ha_mcp.tools.tools_logs import LogTools

from ._error_log_core import call_logs, error_log, numbered_log
from ._error_log_core import log_file as log_file
from ._error_log_routes_core import ErrorLogRoute
from ._error_log_routes_core import journald_route as journald_route
from ._tool_errors import error_of


@pytest.mark.parametrize("offset", ["--5", "²"])
async def test_invalid_offset_is_a_classified_validation_error(
    core_client: HomeAssistantClient, offset: str,
) -> None:
    with pytest.raises(ToolError) as error:
        await LogsFacade(LogTools(core_client).get_logs).ha_get_logs(
            source="error_log", offset=offset
        )
    assert error_of(error)["code"] == "VALIDATION_INVALID_PARAMETER"


async def test_first_short_journal_window_keeps_unreturned_records_pageable(
    journald_route: ErrorLogRoute,
) -> None:
    entries = numbered_log(10).splitlines()
    await journald_route.serve(entries)
    shown = []
    offset = 0
    for _ in range(6):
        page = await call_logs(
            journald_route.client, source="error_log", format="raw", limit=2, offset=offset
        )
        shown.extend(page["log"].splitlines())
        if not page["has_more"]:
            break
        offset = page["next_offset"]
    assert shown == list(reversed(entries))


async def test_missing_supervisor_cursor_is_not_reported_as_complete_history() -> None:
    fetch = AsyncMock(return_value=JournaldPage(numbered_log(4), None))
    page = await journald_page(4, 0, fetch)
    assert not page.pagination_complete
    result = LogTools(None).error_log_result(
        page, 4, 2, None, None, "newest", 1, False, None
    )
    assert result["pagination_complete"] is False
    assert "reached the start" not in json.dumps(result)
    assert "no older history" not in json.dumps(result)


async def test_core_empty_message_still_starts_a_record(
    log_file: Path, core_client: HomeAssistantClient,
) -> None:
    result = await error_log(
        log_file, core_client,
        "2026-10-25 10:00:00.000 INFO (MainThread) [test] previous\n"
        "2026-10-25 10:00:01.000 ERROR (MainThread) [test] \n"
        "Traceback (most recent call last):\nValueError: details\n",
    )
    assert result["total_records"] == 2
    assert "ValueError: details" in result["log"]
