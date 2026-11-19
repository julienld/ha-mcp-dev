"""Read a render subscription's verdict without owning the transport."""

import asyncio
import logging
from typing import Any

from ha_mcp.errors import HomeAssistantConnectionError

logger = logging.getLogger(__name__)

RENDER_NO_VERDICT_WITHOUT_REPORT_ERRORS = (
    "No template result from Home Assistant. With report_errors=false Home "
    "Assistant does not report a failed render (it only writes the error to "
    "its own log), so the template most likely failed. Retry with "
    "report_errors=true to get the error."
)


def _is_typed_template_error(error: str) -> bool:
    """True for ``"UndefinedError: ..."``-style messages that name the class."""
    name = error.partition(": ")[0]
    return name.isidentifier() and name.endswith(("Error", "Exception"))


def _pick_render_error(first: str, queue: asyncio.Queue[dict[str, Any]]) -> str:
    """Choose the clearest of the ERROR events already queued after ``first``.

    One failure can arrive as several events: an undefined attribute is
    reported once bare (``'dict object' has no attribute 'split'``) and once
    with its class (``UndefinedError: ...``). The class-named one is kept.
    """
    candidates = [first]
    while True:
        try:
            event = queue.get_nowait().get("event") or {}
        except asyncio.QueueEmpty, asyncio.QueueShutDown:
            break
        error = event.get("error")
        if event.get("level") == "ERROR" and isinstance(error, str):
            candidates.append(error)
    return next((e for e in candidates if _is_typed_template_error(e)), first)


async def _read_render_verdict(
    queue: asyncio.Queue[dict[str, Any]],
    template: Any,
    wait: float,
    report_errors: bool,
) -> dict[str, Any]:
    """Read ``render_template`` events up to the render's verdict."""
    warnings: list[str] = []
    try:
        async with asyncio.timeout(wait):
            while True:
                event = (await queue.get()).get("event") or {}
                if "result" in event:
                    response: dict[str, Any] = {
                        "success": True,
                        "result": event["result"],
                        "template": template,
                        "listeners": event.get("listeners", {}),
                    }
                    break
                error = event.get("error")
                if not isinstance(error, str):
                    logger.debug("render_template: unrecognised event %r", event)
                    continue
                if event.get("level") == "ERROR":
                    response = {
                        "success": False,
                        "error": _pick_render_error(error, queue),
                        "template": template,
                    }
                    break
                if error not in warnings:
                    warnings.append(error)
    except TimeoutError:
        response = {
            "success": False,
            "error": (
                "Event timeout - template result not received"
                if report_errors
                else RENDER_NO_VERDICT_WITHOUT_REPORT_ERRORS
            ),
            "no_verdict": True,
            "template": template,
        }
    except asyncio.QueueShutDown as e:
        raise HomeAssistantConnectionError(
            "WebSocket connection to Home Assistant closed while rendering the template"
        ) from e
    if warnings:
        response["warnings"] = warnings
    return response
