"""Observe a Core-owned entry reload through the finite watch backend."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

from ha_mcp.utils.owned_executor import await_owned_io

logger = logging.getLogger(__name__)


@asynccontextmanager
async def watch_entry_reload(
    client: Any, entry_id: str
) -> AsyncIterator[Callable[[], Awaitable[dict[str, Any] | None]]]:
    watch = None
    try:
        watch = await client.backend.execute(
            "config.entries.watch", {"entry_id": entry_id}, client.context
        )
    except Exception:
        logger.warning("Entry-change observation unavailable", exc_info=True)

    async def settled() -> dict[str, Any] | None:
        if watch is None:
            return None
        try:
            return cast(
                dict[str, Any] | None,
                await client.backend.execute(
                    "config.entries.observe",
                    {**watch, "entry_id": entry_id},
                    client.context,
                ),
            )
        except Exception:
            logger.warning(
                "Entry-change observation failed after commit", exc_info=True
            )
            return None

    try:
        yield settled
    finally:
        if watch is not None:
            try:
                await await_owned_io(
                    client.backend.execute(
                        "config.entries.close", watch, client.context
                    )
                )
            except Exception as error:  # noqa: BLE001 - cleanup must preserve the outcome
                logger.warning(
                    "Entry-change observation close failed: %s", type(error).__name__
                )
