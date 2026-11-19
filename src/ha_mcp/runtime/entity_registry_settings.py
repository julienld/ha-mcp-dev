"""Shared entity-versus-global parameter admission."""

from typing import Any

from ha_mcp.errors import ErrorCode, create_error_response

from .errors import raise_failure


def is_registry_wide_call(
    entity_id: Any, params: dict[str, Any], entity_params: dict[str, Any]
) -> bool:
    """False when entity_id is given, True for a registry-wide call.

    Raises on a call that mixes the two kinds and on one with neither.
    """
    registry_wide = [k for k, v in params.items() if v is not None]
    if entity_id is not None:
        if registry_wide:
            raise_failure(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    f"{', '.join(registry_wide)} are registry-wide and take no entity_id.",
                    suggestions=[
                        "Send the registry-wide settings in a call without entity_id"
                    ],
                )
            )
        return False
    given = [k for k, v in entity_params.items() if v is not None]
    if given or not registry_wide:
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_MISSING_PARAMETER,
                "entity_id is required"
                + (f" for {', '.join(given)}" if given else "")
                + f"; only {', '.join(params)} take none.",
            )
        )
    return True
