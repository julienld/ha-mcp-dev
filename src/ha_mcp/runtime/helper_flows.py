"""The helper types Home Assistant creates through a config flow, read from Core.

``flow_handlers?type=helper`` lists Core's own helper flows plus custom
integrations of ``integration_type: "helper"`` — the list the HA UI offers under
"Create helper". ``integration/descriptions`` tells Core's own apart from the
custom ones (``core_helper_domains``). Both are cached per client for a few
minutes so a tool call does not pay a round-trip each time; a type missing from
a cached copy is re-read once before it counts as unlisted
(``listed_helper_flows``), so a newly installed helper integration is found.
"""

from __future__ import annotations

import time
import weakref
from typing import Any, NoReturn

from ha_mcp.errors import (
    ErrorCode,
    create_error_response,
)
from ha_mcp.runtime.errors import raise_classified as exception_to_structured_error
from ha_mcp.runtime.errors import raise_failure as raise_tool_error
from ha_mcp.runtime.helper_schema import SIMPLE_HELPER_TYPES
from ha_mcp.tool_api import ToolFailure as ToolError

_TTL_SECONDS = 300.0
_Cache = weakref.WeakKeyDictionary[Any, tuple[float, frozenset[str]]]
_CACHE: _Cache = weakref.WeakKeyDictionary()
_CORE_CACHE: _Cache = weakref.WeakKeyDictionary()


async def _fetch_helper_flow_types(client: Any) -> frozenset[str]:
    result = await client.backend.execute(
        "helpers.flow.types", {"helper_type": "all"}, client.context
    )
    return frozenset(result["types"])


async def _fetch_core_helper_domains(client: Any) -> frozenset[str]:
    result = await client.backend.execute(
        "helpers.flow.core_types", {"helper_type": "all"}, client.context
    )
    return frozenset(result["types"])


def _cached(cache: _Cache, client: Any) -> frozenset[str] | None:
    try:
        cached = cache.get(getattr(client, "cache_owner", client))
    except TypeError:
        return None
    if cached is not None and time.monotonic() - cached[0] < _TTL_SECONDS:
        return cached[1]
    return None


async def _read(
    cache: _Cache, fetch: Any, client: Any, *, refresh: bool
) -> frozenset[str]:
    cached = None if refresh else _cached(cache, client)
    if cached is not None:
        return cached
    domains: frozenset[str] = await fetch(client)
    try:
        cache[getattr(client, "cache_owner", client)] = (time.monotonic(), domains)
    except TypeError:  # a client that cannot be weakly referenced is not cached
        pass
    return domains


async def helper_flow_types(client: Any, *, refresh: bool = False) -> frozenset[str]:
    """The helper types the connected Home Assistant offers as config flows."""
    return await _read(_CACHE, _fetch_helper_flow_types, client, refresh=refresh)


async def core_helper_domains(client: Any) -> frozenset[str]:
    """The helper flows that are Home Assistant's own, not a custom integration's."""
    return await _read(_CORE_CACHE, _fetch_core_helper_domains, client, refresh=False)


async def listed_helper_flows(client: Any, name: str) -> frozenset[str]:
    """The helper flow list, re-read once when ``name`` is missing from a cached
    copy (a fresh read is not repeated)."""
    cached = _cached(_CACHE, client)
    if cached is not None and name in cached:
        return cached
    return await helper_flow_types(client, refresh=cached is not None)


async def require_helper_type(client: Any, helper_type: str, *also: str) -> None:
    """Refuse a helper_type that is neither a storage helper, one of ``also``,
    nor a helper flow this Home Assistant lists. A failed read of that list is
    raised as a structured tool error, never as the raw exception."""
    if helper_type in SIMPLE_HELPER_TYPES or helper_type in also:
        return
    try:
        flow_types = await listed_helper_flows(client, helper_type)
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001
        exception_to_structured_error(
            e,
            context={
                "helper_type": helper_type,
                "operation": "read Home Assistant's helper flow list",
            },
        )
    if helper_type not in flow_types:
        _raise_unknown_helper_type(helper_type, flow_types)


def _raise_unknown_helper_type(
    helper_type: str, flow_types: frozenset[str]
) -> NoReturn:
    raise_tool_error(
        create_error_response(
            ErrorCode.VALIDATION_INVALID_PARAMETER,
            f"Unknown helper_type {helper_type!r}: it is neither a storage helper "
            "nor one of the helper flows this Home Assistant lists.",
            context={"helper_type": helper_type},
            suggestions=[
                "Storage helpers: " + ", ".join(sorted(SIMPLE_HELPER_TYPES)),
                "Helper flows on this instance: " + ", ".join(sorted(flow_types)),
            ],
        )
    )
