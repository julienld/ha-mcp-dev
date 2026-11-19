"""Authenticated remote transport for shared journal-window paging."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from typing import Any

from ha_mcp.tool_api import ToolFailure

from .._version import is_running_in_addon
from ..runtime import journal_window as shared
from ..runtime.journal_window import (
    EPOCH as EPOCH,
)
from ..runtime.journal_window import (
    MAX_ENTRIES,
    JournalPage,
    JournalWindow,
    WindowToken,
)
from ..runtime.journal_window import (
    WINDOW_TOKEN_PREFIX as WINDOW_TOKEN_PREFIX,
)
from ..runtime.journal_window import (
    WindowRestart as WindowRestart,
)
from ..runtime.journal_window import (
    is_window_token as is_window_token,
)
from ..runtime.journal_window import (
    parse_window_token as parse_window_token,
)
from ..runtime.journal_window import (
    window_range as window_range,
)
from ..runtime.journal_window import (
    window_start as window_start,
)
from .error_log_journald import JournaldFetch, JournaldPage, first_cursor
from .rest_client import HomeAssistantAPIError, HomeAssistantConnectionError

_PARAMS = {"no_colors": "true"}

__all__ = [
    "EPOCH",
    "MAX_ENTRIES",
    "WINDOW_TOKEN_PREFIX",
    "JournalPage",
    "JournalWindow",
    "WindowRestart",
    "WindowToken",
    "is_window_token",
    "parse_window_token",
    "read_logs_page",
    "read_logs_window",
    "read_page",
    "read_window",
    "window_range",
    "window_start",
]


async def _fetch(client: Any, path: str, range_header: str) -> JournaldPage:
    """One ``/<path>/logs`` read with ``range_header``, direct or via Core's proxy.

    ``path`` is ``addons/<slug>`` for an app or a system-service name. Core's
    hassio proxy forwards ``Range`` and Supervisor's ``X-First-Cursor`` on its
    log paths.
    """
    headers = {"Accept": "text/plain", "Range": range_header}
    if is_running_in_addon():
        response = await client._supervisor_logs_response(path, headers, dict(_PARAMS))
    else:
        response = await client._raw_request(
            "GET", f"/hassio/{path}/logs", headers=headers, params=dict(_PARAMS)
        )
    return JournaldPage(str(response.text), first_cursor(response))


def _fetcher(client: Any, path: str) -> JournaldFetch:
    def fetch(range_: str) -> Coroutine[Any, Any, JournaldPage]:
        return _fetch(client, path, range_)

    return fetch


async def read_window(
    client: Any, path: str, since: datetime, max_entries: int | None = None
) -> JournalWindow:
    try:
        return await shared.read_window(
            _fetcher(client, path),
            path,
            since,
            MAX_ENTRIES if max_entries is None else max_entries,
        )
    except ToolFailure as error:
        raise HomeAssistantAPIError(str(error)) from error


async def read_page(
    client: Any,
    path: str,
    since: datetime,
    hours_back: int,
    count: int,
    resume: WindowToken | None = None,
    skip: int = 0,
) -> JournalPage:
    try:
        return await shared.read_page(
            _fetcher(client, path), path, since, hours_back, count, resume, skip
        )
    except ToolFailure as error:
        raise HomeAssistantAPIError(str(error)) from error


async def read_logs_window(client: Any, path: str, since: datetime) -> JournalWindow:
    """``read_window`` under one deadline for all of its requests."""
    return await _within_timeout(client, path, since, read_window(client, path, since))


async def read_logs_page(
    client: Any,
    path: str,
    since: datetime,
    hours_back: int,
    count: int,
    resume: WindowToken | None = None,
    skip: int = 0,
) -> JournalPage:
    """``read_page`` under one deadline for all of its requests."""
    return await _within_timeout(
        client,
        path,
        since,
        read_page(client, path, since, hours_back, count, resume, skip),
    )


async def _within_timeout[T](
    client: Any,
    path: str,
    since: datetime,
    read: Coroutine[Any, Any, T],
) -> T:
    try:
        async with asyncio.timeout(client.timeout):
            return await read
    except TimeoutError as e:
        raise HomeAssistantConnectionError(
            f"Timeout reading /{path}/logs from {since.isoformat()} "
            f"after {client.timeout}s"
        ) from e
