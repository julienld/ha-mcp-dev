"""Value comparison and identity disclosure shared by registry recreation."""

from typing import Any

REGISTRY_ITEM_DOMAINS = frozenset({"label", "category", "area_or_floor"})


def registry_fields_match(row: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Compare snapshot fields, treating registry memberships as unordered."""
    for key, expected in payload.items():
        actual = row.get(key)
        if isinstance(actual, (list, tuple, set)) and isinstance(
            expected, (list, tuple, set)
        ):
            if sorted(map(str, actual)) != sorted(map(str, expected)):
                return False
        elif actual != expected:
            return False
    return True


def registry_identity_warning(
    row: dict[str, Any], id_key: str, previous: str
) -> str | None:
    """Explain the references that Core's new registry identity cannot restore."""
    if row.get(id_key) == previous:
        return None
    noun = id_key.removesuffix("_id")
    return (
        f"The {noun} came back as {row.get(id_key)}, not {previous}: anything that refers "
        f"to the {noun} by {previous} still matches nothing."
    )


def note_registry_identity(
    row: dict[str, Any], id_key: str, previous: str
) -> dict[str, Any]:
    """Keep Core's actual identity and disclose that old references stay broken."""
    warning = registry_identity_warning(row, id_key, previous)
    return (
        {**row, "warnings": [*(row.get("warnings") or []), warning]} if warning else row
    )
