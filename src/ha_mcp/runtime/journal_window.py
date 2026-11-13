"""Journal time windows and cursor paging over an authenticated fetch callback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ha_mcp.tool_api import ToolFailure

from .error_log_journald import JournaldFetch, JournaldPage, range_header

MAX_ENTRIES = 10_000

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

WINDOW_TOKEN_PREFIX = "window:"


@dataclass(frozen=True)
class JournalWindow:
    """The entries of a time window, and whether all of them were read."""

    lines: list[str]
    complete: bool
    cap: int


@dataclass(frozen=True)
class JournalPage:
    """One page of a time window; ``next_token`` continues it while ``has_more``."""

    lines: list[str]
    has_more: bool
    next_token: str | None = None


class WindowRestart(Exception):
    """A page token's entry is gone from the journal; the read must start again."""


@dataclass(frozen=True)
class WindowToken:
    """Where a page read resumes: the read's window, and an entry.

    ``since`` is the window's start as the first page computed it, and
    ``hours_back`` the value it was computed from. ``path`` names the log
    stream (``addons/<slug>`` or a system service), so a token cannot be
    carried to another stream, whose journal its cursor does not belong to.
    The next page starts ``skip`` entries after ``cursor``, the first entry of
    the page before.
    """

    since: datetime
    hours_back: int
    path: str
    cursor: str
    skip: int

    def __str__(self) -> str:
        return (
            f"{WINDOW_TOKEN_PREFIX}{_epoch(self.since)}:{self.hours_back}:"
            f"{self.path}:{self.cursor}:{self.skip}"
        )


def is_window_token(value: object) -> bool:
    """True when ``value`` looks like a token ``read_page`` returned."""
    return isinstance(value, str) and value.startswith(WINDOW_TOKEN_PREFIX)


def parse_window_token(token: str) -> WindowToken:
    """Split a page token; raises ``ValueError`` when it is malformed.

    systemd cursors separate their fields with ``;`` and never contain ``:``,
    nor does a log path (it holds ``/`` only), but the skip is still split off
    from the right.
    """
    if not is_window_token(token):
        raise ValueError("not a window token")
    since, _, rest = token[len(WINDOW_TOKEN_PREFIX) :].partition(":")
    hours_back, _, rest = rest.partition(":")
    path, _, rest = rest.partition(":")
    cursor, _, skip = rest.rpartition(":")
    if (
        not since.isdecimal()
        or not hours_back.isdecimal()
        or not path
        or not cursor
        or not skip.isdecimal()
    ):
        raise ValueError(
            "a window token reads 'window:<since>:<hours_back>:<path>:"
            "<cursor>:<skip>' as returned in 'next_offset'"
        )
    try:
        start = datetime.fromtimestamp(int(since), UTC)
    except (OverflowError, ValueError, OSError) as e:
        raise ValueError(f"a window token's start is out of range: {since}") from e
    return WindowToken(start, int(hours_back), path, cursor, int(skip))


def window_start(until: datetime, hours_back: int) -> datetime:
    """``until`` minus ``hours_back`` hours, in whole seconds, no earlier than the epoch.

    Any ``hours_back`` is accepted: one reaching before 1970, or past what
    ``datetime`` can hold, means the whole journal. The start is cut to the
    whole second gatewayd seeks to, so a token carrying it names the same
    start as the first page.
    """
    try:
        start = max(until - timedelta(hours=hours_back), EPOCH)
    except OverflowError:
        return EPOCH
    return start.replace(microsecond=0)


def _epoch(moment: datetime) -> str:
    """Whole seconds since the epoch, gatewayd's default unit for ``realtime=``."""
    return str(int(moment.timestamp()))


def window_range(since: datetime, skip: int, count: int) -> str:
    """``count`` entries from the ``skip``-th entry at or after ``since``.

    ``num_entries`` is always given: systemd 256 answers 400 to a Range whose
    count is empty (systemd#37172, made optional again by systemd#37883).
    """
    return f"realtime={_epoch(since)}::{skip}:{count}"


def _holds_an_entry(page: JournaldPage) -> bool:
    return page.first_cursor is not None or page.text != ""


def _cursor_of(page: JournaldPage, path: str) -> str:
    """The page's first cursor, which paging cannot do without."""
    if not page.first_cursor:
        raise ToolFailure(
            "SERVICE_CALL_FAILED",
            f"Supervisor sent no X-First-Cursor for /{path}/logs, so the "
            "window cannot be paged from an exact entry",
        )
    return page.first_cursor


async def read_window(
    fetch: JournaldFetch,
    path: str,
    since: datetime,
    max_entries: int | None = None,
) -> JournalWindow:
    """The entries of ``/<path>/logs`` from ``since`` to the end of the journal.

    Every entry prints at least one line, so fewer lines than ``max_entries``
    means the window is whole and needs no probe. An entry logged between the
    read and the probe can make the probe report more than there was; that
    errs towards calling a window incomplete, never the other way.
    """
    if max_entries is None:
        max_entries = MAX_ENTRIES
    page = await fetch(window_range(since, 0, max_entries))
    lines = page.text.splitlines()
    if len(lines) < max_entries:
        return JournalWindow(lines, True, max_entries)
    first = _cursor_of(page, path)
    if await _entry_after(fetch, first, max_entries) is None:
        return JournalWindow(lines, True, max_entries)
    page = await fetch(range_header(max_entries))
    return JournalWindow(page.text.splitlines(), False, max_entries)


async def read_page(
    fetch: JournaldFetch,
    path: str,
    since: datetime,
    hours_back: int,
    count: int,
    resume: WindowToken | None = None,
    skip: int = 0,
) -> JournalPage:
    """``count`` entries of the window from ``since``, oldest-first.

    The first page is read without ``resume`` and may start ``skip`` entries
    into the window. Each later page passes the token the page before
    returned. A multi-line entry is returned whole, so a page can hold more
    lines than ``count``. Every entry prints at least one line, so fewer lines
    than ``count`` ends the window.

    A first page that skips into the window starts from the window's first
    entry's cursor, so a skip past the window's end finds nothing rather than
    the journal's last entry.
    """
    if resume is not None:
        await _require_entry(fetch, path, resume.cursor)
        page = await fetch(f"entries={resume.cursor}:{resume.skip}:{count}")
    elif skip:
        first_page = await fetch(window_range(since, 0, 1))
        if not _holds_an_entry(first_page):
            return JournalPage([], False)
        start = await _entry_after(fetch, _cursor_of(first_page, path), skip)
        if not start:
            return JournalPage([], False)
        page = await fetch(f"entries={start}:0:{count}")
    else:
        page = await fetch(window_range(since, 0, count))
    lines = page.text.splitlines()
    if len(lines) < count:
        return JournalPage(lines, False)
    cursor = _cursor_of(page, path)
    if await _entry_after(fetch, cursor, count) is None:
        return JournalPage(lines, False)
    # Entries logged since the page was read can make the probe find one past
    # a page that held fewer than ``count`` entries (multi-line entries reach
    # the line count first). The token skips ``count`` entries, so the page is
    # read again now that ``count`` entries are known to follow its first.
    lines = (await fetch(f"entries={cursor}:0:{count}")).text.splitlines()
    token = WindowToken(since, hours_back, path, cursor, count)
    return JournalPage(lines, True, str(token))


async def _require_entry(fetch: JournaldFetch, path: str, cursor: str) -> None:
    """Refuse a token whose entry has been vacuumed from the journal.

    Gatewayd seeks a missing cursor on to the next entry that is left
    (``sd_journal_seek_cursor``), and a skip would count from there.
    """
    if (await fetch(f"entries={cursor}:0:1")).first_cursor != cursor:
        raise WindowRestart(
            f"The entry this read continues from is no longer in the journal "
            f"of /{path}/logs (it was vacuumed); start a new read"
        )


async def _entry_after(fetch: JournaldFetch, cursor: str, k: int) -> str | None:
    """The cursor of the entry ``k`` (1 or more) entries after ``cursor``, if any."""
    return (await fetch(f"entries={cursor}:{k}:1")).first_cursor
