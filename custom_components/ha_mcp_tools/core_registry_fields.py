"""Introspect the running Core registry schemas and declared entry fields."""

import dataclasses
from datetime import datetime
from typing import Any

import attr
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .core_registries import _category_registry
from .core_registry import (
    _resolve_registries,
    _substrate_unavailable,
    _unambiguous_device_entries,
)


def registry_fields(hass: HomeAssistant, params: dict[str, Any]) -> dict[str, Any]:
    """Name the fields Core's commands take for a registry, and how Core keeps
    the fields of one of its entries.

    Returns ``update_fields`` and ``create_fields`` (the keys of the schemas
    Core registered for ``config/<registry>_registry/update`` and
    ``.../create``, without ``id`` and ``type``; ``create_fields`` is ``None``
    without a create command), and with ``item_id`` the entry's
    ``set_fields`` (declared fields holding a ``set`` or ``frozenset``) and
    ``stamped_fields`` (declared ``datetime`` fields ``update_fields`` does not
    name). Both are ``None`` without ``item_id`` or when Core holds no such
    entry. All lists are sorted. How the server uses them:
    ``docs/agents/native-core-contracts.md`` (Choose the authoritative path).

    Only declared fields are named (read by attribute); a row key that is a
    property, such as a device's deprecated ``config_entries``, is never
    named; on Core 2026.10 and later, reading it reports its use.

    Raises ``HomeAssistantError`` when Core registers no update command for the
    registry, and, with ``item_id``, for a ``category`` without ``scope`` and
    for a registry whose accessor drifted (as :func:`_do_registries`).
    """
    kind = params["registry"]
    update_fields = _command_fields(hass, f"config/{kind}_registry/update")
    if update_fields is None:
        raise HomeAssistantError(
            f"ha_mcp_tools/registry_fields: Core registers no update command "
            f"for the {kind} registry"
        )
    result: dict[str, Any] = {
        "update_fields": update_fields,
        "create_fields": _command_fields(hass, f"config/{kind}_registry/create"),
        "set_fields": None,
        "stamped_fields": None,
    }
    item_id = params.get("item_id")
    if item_id is None:
        return result
    entry = _registry_entry(hass, kind, item_id, params.get("scope"))
    if entry is None:
        return result
    values = {
        field.name: getattr(entry, field.name) for field in declared_fields(entry)
    }
    result["set_fields"] = sorted(
        name for name, value in values.items() if isinstance(value, (set, frozenset))
    )
    result["stamped_fields"] = sorted(
        name
        for name, value in values.items()
        if isinstance(value, datetime) and name not in update_fields
    )
    return result


def _command_fields(hass: HomeAssistant, command: str) -> list[str] | None:
    """The keys of the schema Core registered for ``command``, without the
    transport keys ``id`` and ``type``; None when Core registers no such
    command."""
    registered = (hass.data.get("websocket_api") or {}).get(command)
    if registered is None:
        return None
    return sorted({str(key) for key in registered[1].schema} - {"id", "type"})


def _registry_entry(hass: HomeAssistant, kind: str, item_id: str, scope: Any) -> Any:
    """Core's entry of ``kind`` with ``item_id``, None when Core holds none."""
    if kind == "category":
        if not scope:
            raise HomeAssistantError(
                "ha_mcp_tools/registry_fields: scope is required for a category"
            )
        registry = _category_registry(hass)
        if registry is None:
            raise _substrate_unavailable("category registry")
        return registry.async_get_category(scope=scope, category_id=item_id)
    view = _resolve_registries(hass)
    registry = getattr(view, kind)
    if registry is None:
        raise _substrate_unavailable(f"{kind} registry")
    if kind == "device":
        return _unambiguous_device_entries(view).get(item_id)
    getter = "async_get" if kind == "entity" else f"async_get_{kind}"
    return getattr(registry, getter)(item_id)


def declared_fields(entry: Any) -> Any:
    """The fields a registry entry's class declares (attrs or dataclass). Test
    seam: a test replaces it to stand for a Core release whose entry keeps a
    field differently (a list where today's keeps a set)."""
    cls = type(entry)
    return attr.fields(cls) if attr.has(cls) else dataclasses.fields(cls)


async def read_registry_fields(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    return registry_fields(hass, arguments)
