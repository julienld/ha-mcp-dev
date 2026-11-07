"""Authoritative config-entry projection through finite backend reads."""

from typing import Any, NamedTuple


class ComponentEntries(NamedTuple):
    rows: list[dict[str, Any]]
    secret_scrub_degraded: bool
    type_filtered: bool = False


SCRUB_DEGRADED_WARNING = "secrets.yaml could not be read, so config entry options in this response were not scrubbed of resolved !secret values."


async def fetch_config_entries(client: Any, **query: Any) -> ComponentEntries | None:
    result = await client.backend.execute(
        "integrations.entries",
        {k: v for k, v in query.items() if v is not None},
        client.context,
    )
    if result is None:
        return None
    return ComponentEntries(
        result["entries"],
        result.get("secret_scrub_degraded", False),
        result.get("type_filtered", False),
    )


def _split_component_entry_row(
    row: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Split a component ``config_entries`` row into ``(entry, subentries)``.

    The returned ``entry`` mirrors the legacy REST per-entry shape (plus
    ``unique_id``): the row's Core fields and its already-materialized ``options`` (raw
    persisted, secret-scrubbed), with the nested ``subentries`` list lifted out
    so callers surface subentries at the top level exactly like the legacy
    ``include_subentries`` branch — and never leak them onto ``entry`` when
    subentries were not requested. ``options`` values may be ``"**redacted**"``
    where the component scrubbed a resolved ``!secret``.
    """
    entry = dict(row)
    subentries = entry.pop("subentries", None)
    if not isinstance(subentries, list):
        subentries = []
    return entry, subentries
