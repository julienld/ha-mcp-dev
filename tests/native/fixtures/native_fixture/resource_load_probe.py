"""Observe Core's first resource load without changing its result or replaying it."""

from functools import wraps
from pathlib import Path
from traceback import extract_stack
from typing import Any


def observe_resource_loading(hass: Any, data: dict[str, Any]) -> None:
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    owner = getattr(hass.data.get("lovelace"), "resources", None)
    probe: dict[str, Any] = {
        "initial_owner_type": type(owner).__name__,
        "initial_loaded": getattr(owner, "loaded", None),
        "first_load": None,
    }
    data["resource_load_probe"] = probe
    original = ResourceStorageCollection._async_ensure_loaded

    @wraps(original)
    async def observed(collection: Any) -> Any:
        attempt = None
        if not collection.loaded and probe["first_load"] is None:
            attempt = {
                "owner_type": type(collection).__name__,
                "loaded_before": collection.loaded,
                "stack": [
                    {
                        "file": Path(frame.filename).name,
                        "function": frame.name,
                        "line": frame.lineno,
                    }
                    for frame in extract_stack(limit=35)
                ],
            }
            probe["first_load"] = attempt
        try:
            return await original(collection)
        finally:
            if attempt is not None:
                attempt["loaded_after"] = collection.loaded

    ResourceStorageCollection._async_ensure_loaded = observed
