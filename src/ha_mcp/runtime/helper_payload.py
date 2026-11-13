"""Storage-helper payloads built generically and validated by Core (#2632).

Home Assistant validates a storage helper's create and update against its own
schema, and its messages name the problem and the field ("value must be one of
['box', 'slider'] at 'mode'", "not a valid option, did you mean 'minimum'?").
So the payload is the caller's fields under Core's names, sent as-is; this
module only adds what Core does not do itself.
"""

from __future__ import annotations

from typing import Any

from ha_mcp.errors import ErrorCode, create_error_response

from .errors import raise_failure
from .helper_schema import _simple_helper_error_context
from .validation import clear_or_keep

# The tool's own range parameters, under the names each type's Core schema uses.
_RANGE_KEYS: dict[str, tuple[str, str]] = {"counter": ("minimum", "maximum")}
_DEFAULT_RANGE_KEYS = ("min", "max")


def icon_targets_from_schema(
    helper_type: str, action: str, icon: str | None, schemas: dict[str, Any] | None
) -> tuple[str | None, str | None]:
    """Follow Core's dialog: item icons and registry overrides stay separate."""
    if icon is None:
        return None, None
    fields = schemas.get(helper_type, {}).get(action) if schemas else None
    if isinstance(fields, list):
        if any(
            isinstance(field, dict) and field.get("name") == "icon" for field in fields
        ):
            return icon, None
        return None, icon
    if helper_type == "zone":
        return icon, None
    return (icon, icon) if icon == "" else (None, icon)


def note_hidden_icon(
    entity_id: str, item_icon: str, override: str | None, warnings: list[str]
) -> None:
    """Explain a registry override that hides the icon just stored or cleared."""
    if not override or override == item_icon:
        return
    shown = (
        f"shows its entity registry icon {override} over the stored icon {item_icon}"
        if item_icon
        else f"still shows its entity registry icon {override}"
    )
    warnings.append(
        f"{entity_id} {shown}; clear it with "
        f"ha_set_entity(entity_id='{entity_id}', icon='')."
    )


def note_kept_icon(
    helper_type: str,
    item_icon: str | None,
    updated_data: dict[str, Any],
    warnings: list[str],
) -> None:
    """A zone update keeps an omitted stored icon, as Core's dialog does."""
    if item_icon == "" and updated_data.get("icon"):
        warnings.append(
            f"Home Assistant kept the {helper_type}'s icon "
            f"{updated_data['icon']}: its update keeps a stored icon, as the "
            f"{helper_type} dialog does, so it can be changed but not removed."
        )


def storage_fields(
    helper_type: str, config: Any, name: str | None, icon: str | None
) -> tuple[str | None, str | None, dict[str, Any]]:
    """A storage helper's ``config`` as the fields sent to Core, with its
    name and icon.

    ``config`` goes to Core as written, under Core's own field names: Core
    rejects a key its schema lacks and suggests the closest one. ``name`` and
    ``icon`` are fields of Core's schema too, so ``config`` may carry them.
    """
    if config in (None, ""):
        fields: dict[str, Any] = {}
    elif isinstance(config, dict):
        fields = dict(config)
    else:
        _reject(
            helper_type,
            f"config must be an object for helper_type='{helper_type}': a "
            "storage helper is written in one call.",
        )
    # These address the WebSocket request (its command, the item to update),
    # not a field of the item. A tag's ``tag_id`` is the one that is both:
    # Core's tag create takes it as a field.
    addressing = {"type", "id"} | ({f"{helper_type}_id"} - {"tag_id"})
    if reserved := sorted(addressing & fields.keys()):
        _reject(
            helper_type,
            f"config keys {', '.join(reserved)} address the request, not a "
            f"field of the {helper_type}.",
        )
    top_level = {"name": name, "icon": icon}
    for key, given in top_level.items():
        in_config = fields.pop(key, None)
        if in_config is None:
            continue
        if given is not None and given != in_config:
            _reject(
                helper_type,
                f"'{key}' was passed both as a parameter and in config with "
                "different values.",
            )
        top_level[key] = in_config
    return top_level["name"], clear_or_keep(top_level["icon"], "icon"), fields


def with_create_defaults(helper_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Defaults this tool documents that Core does not apply on create."""
    fields = {key: value for key, value in fields.items() if value is not None}
    if helper_type == "tag":
        fields.setdefault("tag_id", "")
    return fields


def merged_update(
    helper_type: str,
    stored: dict[str, Any],
    name: str | None,
    icon: str | None,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """The stored item plus the changes: Core's update writes the whole item.

    A cleared icon ('') is left out, since Core rejects an empty icon. A tag's
    name lives in the entity registry, and Core's tag update writes the name
    it is sent there: the listed one is not echoed, or a tag that was never
    named would get its default "Tag <id>" pinned as a registry override.
    """
    body = {k: v for k, v in stored.items() if k != "id"}
    if helper_type == "tag":
        body.pop("name", None)
    if name is not None:
        body["name"] = name
    if icon is not None:
        if icon:
            body["icon"] = icon
        else:
            body.pop("icon", None)
    for key, value in fields.items():
        if value is None:
            body.pop(key, None)
        else:
            body[key] = value
    return body


def _reject(helper_type: str, message: str, **context: Any) -> None:
    raise_failure(
        create_error_response(
            ErrorCode.VALIDATION_INVALID_PARAMETER,
            message,
            context=_simple_helper_error_context(helper_type, **context),
        )
    )
