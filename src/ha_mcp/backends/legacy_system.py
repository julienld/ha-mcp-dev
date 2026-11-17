"""Frozen standalone restart/reload acquisition; native execution uses Core owners."""


from typing import Any

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.client.rest_client import HomeAssistantCommandNotSent, HomeAssistantConnectionError
from ha_mcp.runtime.system_values import (
    NAMED_RELOADS,
    RELOAD_WAIT_SECONDS,
    RELOAD_ALL_FAILED_HINT,
    reload_service,
    reload_entry_result,
    reload_target_result,
)
from ha_mcp.tools.helpers import exception_to_structured_error, raise_tool_error, raise_core_refusal
from ha_mcp.tool_api import ToolFailure
from ha_mcp.tools.system_restart import restart_home_assistant


class LegacySystemActions:
    _client: Any

    async def _restart_call(self, safe_mode: bool = False) -> dict[str, Any]:
        return await restart_home_assistant(
            self._client, confirm=True, safe_mode=safe_mode
        )

    async def _reload_call(self, target: str, entry_id: str | None) -> dict[str, Any]:
        if entry_id is not None:
            return await self._reload_config_entry(entry_id)
        try:
            reloadable = []
            if target not in NAMED_RELOADS:
                reloadable = [
                    entry["domain"]
                    for entry in await self._client.get_services()
                    if "reload" in entry["services"]
                ]
            domain, service = reload_service(target, reloadable)
            await self._call_reload(target, domain, service)
            return reload_target_result(target, domain, service)
        except (ToolError, ToolFailure):
            raise
        except Exception as error:  # noqa: BLE001
            exception_to_structured_error(
                error,
                context={"target": target},
                suggestions=["Check Home Assistant logs for details"],
            )
            raise

    async def _call_reload(self, target: str, domain: str, service: str) -> None:
        """Core owns the reload; WebSocket preserves its refusal code."""
        try:
            reply = await self._client.send_websocket_message(
                {
                    "type": "call_service",
                    "domain": domain,
                    "service": service,
                    "_wait_timeout": max(float(self._client.timeout), RELOAD_WAIT_SECONDS),
                }
            )
        except HomeAssistantCommandNotSent:
            raise
        except HomeAssistantConnectionError as error:
            raise_tool_error(
                create_error_response(
                    ErrorCode.SERVICE_CALL_FAILED,
                    f"{domain}.{service} got no answer, so whether Home Assistant "
                    f"reloaded is unknown: {error}",
                    context={"target": target, "write_outcome_unknown": True},
                    suggestions=[
                        "Home Assistant may still be reloading: check its log before reloading again"
                    ],
                )
            )
        if reply.get("success"):
            return
        suggestions = [
            "Fix what Home Assistant reported, then reload again",
            "Check Home Assistant logs for details",
        ]
        if target == "all":
            suggestions.append(RELOAD_ALL_FAILED_HINT)
        raise_core_refusal(
            f"{domain}.{service} failed", reply, {"target": target}, suggestions
        )

    async def _reload_config_entry(self, entry_id: str) -> dict[str, Any]:
        """Reload a single config entry via the REST config-entries endpoint.

        POSTs to ``/config/config_entries/entry/{entry_id}/reload`` through the
        REST client's generic request method — the ``/entry/`` path segment the
        hand-rolled workaround in issue #1813 was easy to get wrong. A 404
        surfaces as a not-found error naming the ``entry_id``; other failures
        route through the shared exception classifier. Returns the tool's
        standard envelope plus ``reloaded``/``entry_id``.
        """
        try:
            resp = await self._client._request(
                "POST", f"/config/config_entries/entry/{entry_id}/reload"
            )
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            # Local import mirrors ``_reraise_if_fatal``: rest_client imports
            # from the tool helpers transitively, so a module-level import
            # would risk a circular import in the tools package.
            from ..client.rest_client import HomeAssistantAPIError

            if isinstance(e, HomeAssistantAPIError) and e.status_code == 404:
                raise_tool_error(
                    create_error_response(
                        ErrorCode.RESOURCE_NOT_FOUND,
                        f"Config entry not found: {entry_id}",
                        context={"entry_id": entry_id},
                        suggestions=[
                            "Verify the entry_id via ha_get_integration",
                        ],
                    )
                )
            if isinstance(e, HomeAssistantAPIError) and e.status_code == 403:
                # Core returns 403 "Entry cannot be reloaded" for
                # OperationNotAllowed — an entry whose integration does not
                # support reload — not an auth problem.
                raise_tool_error(
                    create_error_response(
                        ErrorCode.SERVICE_CALL_FAILED,
                        f"Config entry {entry_id} cannot be reloaded "
                        "(the integration does not support reload)",
                        context={"entry_id": entry_id},
                        suggestions=[
                            "Restart Home Assistant (ha_restart) to apply "
                            "changes to this integration",
                        ],
                    )
                )
            exception_to_structured_error(
                e,
                context={"entry_id": entry_id},
                suggestions=[
                    "Verify the entry_id via ha_get_integration",
                    "Check Home Assistant logs for details",
                ],
            )

        # Core reports require_restart=True when the entry could not be
        # hot-reloaded (its state is not recoverable) — a success response
        # that still needs a restart to take effect.
        require_restart = isinstance(resp, dict) and bool(resp.get("require_restart"))
        return reload_entry_result(entry_id, require_restart)
