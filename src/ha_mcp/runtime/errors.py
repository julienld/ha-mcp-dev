"""Use the established public error envelopes without importing a transport."""

from typing import Any, NoReturn

from ha_mcp.errors import ErrorCode, create_error_response, is_service_outcome_unknown
from ha_mcp.runtime.error_text import core_error_message
from ha_mcp.tool_api import ToolFailure


def raise_failure(payload: dict[str, Any], *, status: str | None = None) -> NoReturn:
    error = payload.get("error", {})
    raise ToolFailure(
        error.get("code", "TOOL_ERROR") if isinstance(error, dict) else "TOOL_ERROR",
        error.get("message", "Tool failed") if isinstance(error, dict) else str(error),
        data=payload,
        status=status,
    )


def raise_classified(
    error: Exception,
    context: dict[str, Any] | None = None,
    *,
    suggestions: list[str] | None = None,
) -> NoReturn:
    """Keep the historical classifier without depending on MCP or a client."""
    from .error_classification import classified_error

    if isinstance(error, ToolFailure):
        raise error
    raise_failure(
        classified_error(error, context, suggestions=suggestions),
        status="outcome_unknown" if is_service_outcome_unknown(error) else None,
    )


def ws_failure_code(result: dict[str, Any]) -> ErrorCode:
    """Map Core's WS error code: ``invalid_format``, ``service_validation_error``
    and ``not_supported`` (e.g. ``todo/item/move`` on a list without
    reordering) refuse the caller's input; ``not_found`` is an item Core does
    not hold (e.g. a YAML-configured helper)."""
    code = result.get("error_code")
    if code in (
        "invalid_format",
        "invalid_info",
        "service_validation_error",
        "not_supported",
    ):
        return ErrorCode.VALIDATION_INVALID_PARAMETER
    if code == "not_found":
        return ErrorCode.RESOURCE_NOT_FOUND
    return ErrorCode.SERVICE_CALL_FAILED


def websocket_error_message(error: Any) -> str:
    """Extract a readable message from a Home Assistant websocket error."""
    if isinstance(error, dict):
        return str(error.get("message", error))
    return str(error)


def raise_core_refusal(
    what: str,
    result: dict[str, Any],
    context: dict[str, Any] | None = None,
    suggestions: list[str] | None = None,
    suffix: str = "",
) -> NoReturn:
    """Raise a failed WebSocket command as ``{what}: <error>{suffix}``, the
    error without the client's prefix, coded by :func:`ws_failure_code` with
    Core's own code kept as ``ha_error_code``."""
    raise_failure(
        create_error_response(
            ws_failure_code(result),
            f"{what}: {core_error_message(result.get('error', 'Unknown error'))}{suffix}",
            suggestions=suggestions,
            context={**(context or {}), "ha_error_code": result.get("error_code")},
        )
    )
