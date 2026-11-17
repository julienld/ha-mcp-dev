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


def compare_core_registry_row(current: dict[str, Any], stored: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    """Normalize only sets and timestamps identified by the running Core owner."""
    result = dict(current)
    for key in fields["set_fields"] or ():
        if key in stored and key in result and registry_fields_match({key: result[key]}, {key: stored[key]}):
            result[key] = stored[key]
    for key in fields["stamped_fields"] or ():
        result.pop(key, None)
        if key in stored:
            result[key] = stored[key]
    return result

def note_restore_omissions(row: dict[str, Any], stored: dict[str, Any], sent: dict[str, Any], fields: dict[str, Any], kind: str, action: str) -> dict[str, Any]:
    """Disclose snapshot values the running Core command cannot restore."""
    writable = {*fields["update_fields"], *(fields["create_fields"] or ())}
    omitted = sorted(key for key in stored if key not in sent and (key in writable or key not in row))
    if not omitted:
        return row
    warning = f"Not restored: {', '.join(omitted)}. The backup holds a value for each, and Home Assistant's command to {action} a {kind} does not take it."
    return {**row, "warnings": [*(row.get("warnings") or []), warning]}