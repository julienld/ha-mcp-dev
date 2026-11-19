"""Publish file authority only after tools-entry setup, retaining failed drains."""

from collections.abc import Awaitable, Callable
from typing import Any

from ha_mcp.utils.owned_executor import await_owned_io

from .const import DOMAIN
from .file_access import DATA_FILE_ACCESS, FileAccess


async def _discard_owner(data: dict[str, Any], owner: FileAccess) -> None:
    await owner.async_stop()
    if data.get(DATA_FILE_ACCESS) is owner:
        data.pop(DATA_FILE_ACCESS)


async def setup_file_entry(
    hass: Any, entry: Any, setup: Callable[[Any, Any], Awaitable[bool]]
) -> bool:
    data = hass.data.setdefault(DOMAIN, {})
    previous = data.get(DATA_FILE_ACCESS)
    if isinstance(previous, FileAccess):
        await await_owned_io(_discard_owner(data, previous))

    owner = FileAccess(hass, entry=entry)
    owner.active = False
    # Service builders must bind this exact owner while setup is in progress.
    data[DATA_FILE_ACCESS] = owner
    unsubscribe: Callable[[], None] | None = None
    stopping = False

    def remove_listener() -> None:
        nonlocal unsubscribe
        if unsubscribe is not None:
            callback, unsubscribe = unsubscribe, None
            callback()

    async def stop(_event: Any) -> None:
        nonlocal stopping
        stopping = True
        await owner.async_stop()

    async def discard() -> None:
        await _discard_owner(data, owner)
        remove_listener()

    try:
        unsubscribe = hass.bus.async_listen_once("homeassistant_stop", stop)
        entry.async_on_unload(remove_listener)
        loaded = await setup(hass, entry)
        if loaded and (data.get(DATA_FILE_ACCESS) is not owner or stopping):
            raise RuntimeError("File authority changed during entry setup")
    except BaseException:
        # A failed drain keeps the inactive owner reachable for a later retry.
        await await_owned_io(discard())
        raise
    if loaded:
        owner.active = True
    else:
        await await_owned_io(discard())
    return loaded
