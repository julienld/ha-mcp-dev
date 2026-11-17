"""Full entity registry rows and exposure reads from installed Core owners."""

from collections import Counter
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ha_mcp.errors import (
    ErrorCode,
    create_entity_not_found_error,
    create_error_response,
)
from ha_mcp.runtime.entity_records import _parse_get_entity_ids
from ha_mcp.runtime.errors import raise_failure

from ..core_entity_reads import enrich_entities, entity_exposure
from .entity_settings import entity_payload, exposure_default, registry_settings
from .registry_access import registry_json


def _enriched_rows(
    hass: HomeAssistant, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    enrichment = enrich_entities(hass, [row["entity_id"] for row in rows])["entities"]
    return [
        {
            **registry_json(row),
            "area": enrichment[row["entity_id"]]["area"],
            "floor": enrichment[row["entity_id"]]["floor"],
            "label_names": enrichment[row["entity_id"]]["labels"],
            "full_name": enrichment[row["entity_id"]]["full_name"],
        }
        for row in rows
    ]


def unregistered_entity(
    hass: HomeAssistant, entity_id: str, exposed: dict[str, Any]
) -> dict[str, Any] | None:
    state = hass.states.get(entity_id)
    key = (
        state.entity_id
        if state is not None
        else entity_id
        if entity_id in exposed
        else None
    )
    if key is None:
        return None
    settings = exposed.get(key) or {}
    return {
        "entity_id": entity_id,
        "entity_entry": None,
        "exposed_to": settings,
        "is_exposed_anywhere": bool(settings),
    }


def _read_mode(arguments: dict[str, Any]) -> None:
    entity_id, unique_id = arguments.get("entity_id"), arguments.get("unique_id")
    if arguments.get("exposed_to") is not None and (
        entity_id is not None or unique_id is not None
    ):
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "exposed_to lists the exposed entities; it takes no entity_id or unique_id.",
            )
        )
    if unique_id is not None and entity_id is not None:
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "Provide exactly one of entity_id or unique_id, not both.",
            )
        )
    if unique_id is None and (
        arguments.get("domain") is not None or arguments.get("platform") is not None
    ):
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "domain/platform are resolver filters — they only apply when unique_id is provided.",
            )
        )


def _resolve_unique(hass: HomeAssistant, arguments: dict[str, Any]) -> dict[str, Any]:
    unique_id, domain, platform = (
        arguments["unique_id"],
        arguments.get("domain"),
        arguments.get("platform"),
    )
    rows = [
        entry.extended_dict
        for entry in er.async_get(hass).entities.values()
        if entry.unique_id == unique_id
        and (domain is None or entry.domain == domain)
        and (platform is None or entry.platform == platform)
    ]
    if not rows:
        raise_failure(
            create_error_response(
                ErrorCode.ENTITY_NOT_FOUND,
                f"No entity found with unique_id '{unique_id}'",
                context={"unique_id": unique_id},
            )
        )
    result: dict[str, Any] = {
        "success": True,
        "unique_id": unique_id,
        "matches": len(rows),
        "entity_entries": _enriched_rows(hass, rows),
    }
    if domain is not None:
        result["domain"] = domain
    if platform is not None:
        result["platform"] = platform
    return result


def _registry_wide(hass: HomeAssistant, assistant: str | None) -> dict[str, Any]:
    default = None if assistant is None else exposure_default(hass, assistant)
    payload = entity_exposure(hass)
    exposed = payload["exposed_entities"]
    filtered = (
        exposed
        if assistant is None
        else {eid: values for eid, values in exposed.items() if values.get(assistant)}
    )
    result: dict[str, Any] = {
        "success": True,
        "settings": registry_settings(hass),
        "exposed_entities": filtered,
        "count": len(filtered),
    }
    if assistant is None:
        result["summary"] = dict(
            Counter(a for values in filtered.values() for a in values)
        )
    if payload["entity_info"]:
        result["entity_info"] = {
            eid: payload["entity_info"][eid]
            for eid in filtered
            if eid in payload["entity_info"]
        }
    if assistant is not None:
        result.update(assistant=assistant, expose_new_entities=default)
    return result


def _read_chunk(
    hass: HomeAssistant, ids: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    normalized = entity_payload(
        hass, "config/entity_registry/get_entries", {"entity_ids": ids}
    )["entity_ids"]
    registry = er.async_get(hass)
    rows: list[dict[str, Any]] = []
    unregistered: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    exposed: dict[str, Any] | None = None
    for original, normalized_id in zip(ids, normalized, strict=True):
        if (entry := registry.async_get(normalized_id)) is not None:
            rows.append(entry.extended_dict)
            continue
        if exposed is None:
            exposed = entity_exposure(hass)["exposed_entities"]
        row = unregistered_entity(hass, original, exposed)
        if row is None:
            errors.append({"entity_id": original, "error": "Entity not found"})
        else:
            unregistered.append(row)
    return rows, unregistered, errors


def _read_ids(hass: HomeAssistant, entity_id: str | list[str]) -> dict[str, Any]:
    from ha_mcp.tool_api import ToolFailure

    ids, bulk, early = _parse_get_entity_ids(entity_id)
    if early is not None:
        return early
    rows: list[dict[str, Any]] = []
    unregistered: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        try:
            found, known, missing = _read_chunk(hass, chunk)
        except ToolFailure as error:
            if not bulk:
                raise
            errors.extend({"entity_id": eid, "error": str(error)} for eid in chunk)
        else:
            rows.extend(found)
            unregistered.extend(known)
            errors.extend(missing)
    rows = _enriched_rows(hass, rows)
    if not bulk:
        if errors:
            raise_failure(create_entity_not_found_error(ids[0]))
        return (
            {"success": True, "entity_id": ids[0], "entity_entry": rows[0]}
            if rows
            else {"success": True, **unregistered[0]}
        )
    result: dict[str, Any] = {
        "success": True,
        "count": len(rows),
        "entity_entries": rows,
    }
    if unregistered:
        result["unregistered_entities"] = unregistered
    if errors:
        result["errors"] = errors
        result["suggestions"] = [
            "Use ha_search() to find valid entity IDs for failed lookups"
        ]
    return result


async def discover_entities(
    hass: HomeAssistant, arguments: dict[str, Any]
) -> dict[str, Any]:
    _read_mode(arguments)
    if arguments.get("unique_id") is not None:
        return _resolve_unique(hass, arguments)
    if arguments.get("entity_id") is None:
        return _registry_wide(hass, arguments.get("exposed_to"))
    return _read_ids(hass, arguments["entity_id"])
