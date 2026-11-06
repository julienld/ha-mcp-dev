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
    owner_type = (
        type(owner)
        if isinstance(owner, ResourceStorageCollection)
        else ResourceStorageCollection
    )
    original = owner_type.async_load

    @wraps(original)
    async def observed(collection: Any, *args: Any, **kwargs: Any) -> Any:
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
            return await original(collection, *args, **kwargs)
        finally:
            if attempt is not None:
                attempt["loaded_after"] = collection.loaded

    owner_type.async_load = observed
