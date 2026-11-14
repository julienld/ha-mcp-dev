"""Core-owned registry settings and assistant defaults, without a transport."""

from typing import Any

from homeassistant.components.homeassistant import exposed_entities
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ha_mcp.runtime.errors import raise_failure
from ha_mcp.runtime.mutation_guard import check_mutation_admission
from ha_mcp.tool_api import CallContext, ToolFailure
from ha_mcp.utils.registry_update_lock import registry_update_lock

from .command_validation import _validated_payload
from .registry_access import Authorize, admit_registry_write, registry_json
from .registry_failures import registry_outcome_unknown


def entity_payload(
    hass: HomeAssistant, command: str, values: dict[str, Any]
) -> dict[str, Any]:
    """Keep Core's installed validator and the public entity refusal category."""
    try:
        return _validated_payload(hass, command, values)
    except ToolFailure as error:
        if error.code != "VALIDATION_FAILED":
            raise
        details = error.data["error"]
        assert isinstance(details, dict)
        payload = {
            **error.data,
            "error": {**details, "code": "VALIDATION_INVALID_PARAMETER"},
        }
        raise_failure(payload, status="not_started")


def exposure_default(hass: HomeAssistant, assistant: str) -> bool:
    values = entity_payload(
        hass, "homeassistant/expose_new_entities/get", {"assistant": assistant}
    )
    owner = hass.data[exposed_entities.DATA_EXPOSED_ENTITIES]
    return bool(owner.async_get_expose_new_entities(values["assistant"]))


async def read_exposure_default(hass: HomeAssistant, arguments: dict[str, Any]) -> bool:
    return exposure_default(hass, arguments["assistant"])


def registry_settings(hass: HomeAssistant) -> dict[str, Any]:
    return registry_json(
        {"entity_id_parts": er.async_get(hass).settings.entity_id_parts}
    )


async def write_registry_settings(
    hass: HomeAssistant,
    actor: CallContext,
    authorize: Authorize,
    expose_new_entities: dict[str, bool] | None,
    entity_id_parts: list[str] | None,
) -> dict[str, Any]:
    """Validate all writes first, retain Core's preimages, then commit synchronously."""
    from ha_mcp.errors import ErrorCode, create_error_response
    from ha_mcp.runtime.entity_parameters import _parse_expose_to_param

    parsed = _parse_expose_to_param(expose_new_entities, "expose_new_entities") or {}
    if not parsed and entity_id_parts is None:
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "expose_new_entities names no assistant; nothing to change.",
            )
        )
    async with registry_update_lock("entity_registry_settings", "global"):
        await admit_registry_write(actor, authorize)
        registry = er.async_get(hass)
        owner = hass.data[exposed_entities.DATA_EXPOSED_ENTITIES]
        settings = (
            None
            if entity_id_parts is None
            else entity_payload(
                hass,
                "config/entity_registry/settings/update",
                {"entity_id_parts": entity_id_parts or None},
            )
        )
        writes = [
            entity_payload(
                hass,
                "homeassistant/expose_new_entities/set",
                {"assistant": assistant, "expose_new": value},
            )
            for assistant, value in parsed.items()
        ]
        previous: dict[str, Any] = {}
        if parsed:
            previous["previous_expose_new_entities"] = {
                a: exposure_default(hass, a) for a in parsed
            }
        if settings is not None:
            previous["previous_settings"] = registry_settings(hass)
        return _commit_settings(
            hass, actor, registry, owner, settings, writes, previous, parsed
        )


def _guard_settings(
    hass: HomeAssistant,
    actor: CallContext,
    registry: Any,
    owner: Any,
    previous: dict[str, Any],
    applied: list[str],
) -> None:
    try:
        check_mutation_admission(actor)
        if (
            er.async_get(hass) is not registry
            or hass.data[exposed_entities.DATA_EXPOSED_ENTITIES] is not owner
        ):
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "The Core registry settings owner changed",
                status="not_started",
            )
    except ToolFailure as error:
        error.data.update(
            {**previous, "applied": list(applied), "partial": bool(applied)}
        )
        if applied:
            error.status = "confirmed"
        raise


def _commit_settings(
    hass: HomeAssistant,
    actor: CallContext,
    registry: Any,
    owner: Any,
    settings: dict[str, Any] | None,
    writes: list[dict[str, Any]],
    previous: dict[str, Any],
    parsed: dict[str, bool],
) -> dict[str, Any]:
    response: dict[str, Any] = {"success": True, **previous}
    applied: list[str] = []

    if settings is not None:
        _guard_settings(hass, actor, registry, owner, previous, applied)
        try:
            registry.async_update_settings(**settings)
            response["settings"] = registry_settings(hass)
            if response["settings"]["entity_id_parts"] != registry_json(
                settings["entity_id_parts"]
            ):
                raise RuntimeError("Core did not confirm the requested entity ID parts")
        except Exception as error:  # noqa: BLE001 - Core listeners may have committed before raising
            registry_outcome_unknown(
                "entity settings",
                "update",
                error,
                context={**previous, "applied": list(applied)},
            )
        applied.append("entity_id_parts")
    for write in writes:
        _guard_settings(hass, actor, registry, owner, previous, applied)
        try:
            owner.async_set_expose_new_entities(write["assistant"], write["expose_new"])
            if exposure_default(hass, write["assistant"]) is not write["expose_new"]:
                raise RuntimeError(
                    "Core did not confirm the requested assistant default"
                )
        except Exception as error:  # noqa: BLE001 - Core save may fail after committing the preference
            registry_outcome_unknown(
                "entity settings",
                "update",
                error,
                context={**previous, "applied": list(applied)},
            )
        applied.append("expose_new_entities." + write["assistant"])
    if parsed:
        response["expose_new_entities"] = parsed
    return response
