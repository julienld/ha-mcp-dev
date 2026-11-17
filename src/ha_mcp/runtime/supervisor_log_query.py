"""Supervisor log result and paging policy shared by Core and remote owners."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from ha_mcp.errors import ErrorCode, create_error_response

from .errors import raise_failure
from .journal_window import WindowRestart, parse_window_token, window_start
from .log_common import (
    DEFAULT_LOG_LIMIT,
    MAX_LIMIT,
    SUPERVISOR_SEARCH_WINDOW_LINES,
    _coerce_limit,
)


class SupervisorLogQuery:
    read_journal_page: Any
    read_journal_window: Any

    @staticmethod
    def _window_call(
        source: str,
        slug: str,
        hours_back: int,
        limit: int,
        offset: str | None = None,
    ) -> str:
        """A copyable page read of the window, continuing from ``offset`` if given."""
        call = (
            f"ha_get_logs(source={source!r}, slug={slug!r}, "
            f"hours_back={hours_back}, order='oldest', limit={limit}"
        )
        if offset is not None:
            call += f", offset={offset!r}"
        return call + ")"

    async def _journal_page(
        self,
        source: str,
        slug: str,
        path: str,
        hours_back: int | None,
        order: Literal["newest", "oldest"] | None,
        limit: int,
        offset: int | str,
        now: datetime | None,
    ) -> dict[str, Any]:
        """One page of the window, oldest-first, served by the journal and continued by token.

        The first page starts at the window's first entry, or an integer
        ``offset`` entries in. A later page passes the ``next_offset`` token
        back: it carries the window's start, the first entry of the page
        before and a skip from it, so the window does not move between calls.
        The journal serves a window oldest-first only, so ``order='newest'``
        is answered oldest-first with a warning.
        """
        read_at = now or datetime.now(UTC)
        resume = None
        warnings: list[str] = []
        if order == "newest":
            warnings.append(
                "A time window (hours_back) is served oldest-first: the journal "
                "selects it from its start and pages forward. order='newest' was "
                "not applied; omit hours_back for the newest lines."
            )
        if isinstance(offset, str):
            resume = parse_window_token(offset)
            if resume.path != path:
                raise_failure(
                    create_error_response(
                        ErrorCode.VALIDATION_INVALID_PARAMETER,
                        f"This 'offset' token continues the log of '{resume.path}'"
                        f", not '{path}'; pass the slug it came from, or start "
                        "a new read without the token",
                    )
                )
            if hours_back is not None and hours_back != resume.hours_back:
                warnings.append(
                    f"hours_back={hours_back} does not match the window this "
                    f"'offset' token continues (hours_back={resume.hours_back}, "
                    f"from {resume.since.isoformat(timespec='seconds')}); the "
                    "token's window is kept. Start a new read without the "
                    "token for a different window."
                )
            since, hours_back = resume.since, resume.hours_back
        else:
            assert hours_back is not None  # routed here only with hours_back
            since = window_start(read_at, hours_back)
        try:
            page = await self.read_journal_page(
                path,
                since,
                hours_back,
                limit,
                resume,
                offset if isinstance(offset, int) else 0,
            )
        except WindowRestart as e:
            raise_failure(
                create_error_response(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    str(e),
                    context={"source": source, "slug": slug},
                    suggestions=[
                        "Start a new read without 'offset': "
                        + self._window_call(source, slug, hours_back, limit)
                    ],
                )
            )
        data: dict[str, Any] = {
            "success": True,
            "source": source,
            "slug": slug,
            "log": "\n".join(page.lines),
            "total_lines": len(page.lines),
            "returned_lines": len(page.lines),
            "limit": limit,
            "order": "oldest",
            "offset": offset,
            "hours_back": hours_back,
            "window_start": since.isoformat(timespec="seconds"),
            "read_at": read_at.isoformat(timespec="seconds"),
            "has_more": page.has_more,
        }
        if warnings:
            data["warnings"] = warnings
        if page.next_token is not None:
            data["next_offset"] = page.next_token
            data["pagination_hint"] = (
                "More entries of the window follow. To continue, use: "
                + self._window_call(source, slug, hours_back, limit, page.next_token)
            )
        return data

    async def _journal_window(
        self, path: str, hours_back: int, now: datetime | None
    ) -> tuple[list[str], dict[str, Any], int]:
        """The window's entries up to the cap, fields describing the read, and the cap.

        The journal selects the window (``realtime=`` Range) from its start
        to the journal's end. ``window_complete`` says whether every entry of
        the window was read; a window too large to read whole also says so in
        a warning, so a partial search is not mistaken for a whole one.
        ``read_at`` is when the read started: entries logged while it ran are
        included.
        """
        read_at = now or datetime.now(UTC)
        since = window_start(read_at, hours_back)
        read = await self.read_journal_window(path, since)
        fields: dict[str, Any] = {
            "hours_back": hours_back,
            "window_start": since.isoformat(timespec="seconds"),
            "read_at": read_at.isoformat(timespec="seconds"),
            "window_complete": read.complete,
        }
        if not read.complete:
            fields["warnings"] = [
                f"The {hours_back}-hour window holds more than {read.cap} "
                f"entries; only the newest {read.cap} were searched, so older "
                "entries in the window were not."
            ]
        return read.lines, fields, read.cap

    def _search_paging(
        self,
        source: str,
        slug: str,
        fields: dict[str, Any],
        cap: int,
        unreturned: int,
        limit: int,
    ) -> dict[str, Any]:
        """``has_more`` and a hint for a search of the window, which offset does not page."""
        complete = fields["window_complete"]
        paging: dict[str, Any] = {"has_more": unreturned > 0 or not complete}
        if not complete:
            start = self._window_call(source, slug, fields["hours_back"], limit)
            paging["pagination_hint"] = (
                f"Only the newest {cap} entries of the window were searched; "
                "its older entries cannot be searched in one read. To read the "
                f"whole window page by page from its first entry, without "
                f"search, use: {start}"
            )
        elif unreturned:
            paging["pagination_hint"] = (
                f"{unreturned} more matching lines in this window; raise limit "
                f"(max {MAX_LIMIT}) or narrow 'search'."
            )
        return paging

    async def _read_service_log(
        self,
        source: str,
        slug: str,
        path: str,
        limit: int | None,
        search: str | None,
        order: Literal["newest", "oldest"] | None,
        hours_back: int | None,
        offset: int | str,
        now: datetime | None,
        read_tail: Callable[[int], Awaitable[str]],
    ) -> dict[str, Any]:
        """The log of an app or system service, by one of three routes.

        Without ``hours_back``: the newest lines, read through ``read_tail``
        (Supervisor's tail, sized to ``limit`` or the search window). With
        ``hours_back`` (or a ``next_offset`` token) and no search: one page of
        the window, oldest-first, served by the journal, so any part of the
        window can be reached. With ``hours_back`` and a search: the whole
        window, up to ``MAX_ENTRIES`` entries, searched, newest matches shown;
        ``offset`` does not apply there.
        """
        effective_limit = _coerce_limit(
            limit, default=DEFAULT_LOG_LIMIT, suggestion_example="100"
        )
        if not search and (hours_back is not None or isinstance(offset, str)):
            return await self._journal_page(
                source, slug, path, hours_back, order, effective_limit, offset, now
            )

        order = order or "newest"
        window: dict[str, Any] = {}
        cap = 0
        if hours_back is not None:
            lines, window, cap = await self._journal_window(path, hours_back, now)
        else:
            # Supervisor's /logs endpoints default to their last 100 lines,
            # so the tail is sized to the caller's limit (found via #1721's
            # e2e), or to the search window when filtering.
            log_text = await read_tail(
                max(effective_limit, SUPERVISOR_SEARCH_WINDOW_LINES)
                if search
                else effective_limit
            )
            lines = log_text.splitlines() if log_text else []

        filters_applied: dict[str, str] = {}
        if search:
            search_lower = search.lower()
            lines = [ln for ln in lines if search_lower in ln.lower()]
            filters_applied["search"] = search

        total_lines = len(lines)
        # The newest lines of what was read; 'order' sets their direction.
        lines = lines[-effective_limit:]
        if order == "newest":
            lines = list(reversed(lines))

        data: dict[str, Any] = {
            "success": True,
            "source": source,
            "slug": slug,
            "log": "\n".join(lines),
            "total_lines": total_lines,
            "returned_lines": len(lines),
            "limit": effective_limit,
            "order": order,
        }
        if filters_applied:
            data["filters_applied"] = filters_applied
        if hours_back is not None:
            data.update(window)
            data.update(
                self._search_paging(
                    source,
                    slug,
                    window,
                    cap,
                    total_lines - len(lines),
                    effective_limit,
                )
            )
        return data
