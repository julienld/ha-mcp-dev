"""
Trace retrieval tools for debugging Home Assistant automations and scripts.

This module provides tools for retrieving execution traces from Home Assistant
to help debug automation and script issues.
"""

import logging
from typing import Any, Literal

from ha_mcp._vendor.fastmcp import Context
from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp._vendor.fastmcp.tools import tool
from ha_mcp.backends.legacy import legacy_errors, legacy_errors_sync
from ha_mcp.runtime import trace_results as _shared_trace

from ..client.rest_client import HomeAssistantError
from ..errors import ErrorCode, create_error_response
from ..runtime.trace_tools import TraceFacade
from .helpers import (
    exception_to_structured_error,
    extract_tool_error_message,
    log_tool_usage,
    raise_tool_error,
    register_tool_methods,
    safe_progress,
)
from .tool_hints import read_only_hints
from .trace_diagnostics import _gather_diagnostics
from .trace_logbook import TraceLogbook, fetch_trace_logbook
from .trace_lookup import (
    ContextTraceMatch,
    _raise_trace_ws_failure,
    _requested_sections,
    resolve_context_trace,
    resolve_global_context,
)

_validate_trace_request = legacy_errors_sync(_shared_trace._validate_trace_request)
_trace_start = _shared_trace._trace_start
_format_trace_list = legacy_errors_sync(_shared_trace._format_trace_list)
_format_detailed_trace = legacy_errors_sync(_shared_trace._format_detailed_trace)
_filter_trace_sections = legacy_errors_sync(_shared_trace._filter_trace_sections)

logger = logging.getLogger(__name__)


def _entity_domain(entity_id: str) -> Literal["automation", "script"]:
    if entity_id.startswith("automation."):
        return "automation"
    if entity_id.startswith("script."):
        return "script"
    raise_tool_error(
        create_error_response(
            ErrorCode.VALIDATION_INVALID_PARAMETER,
            f"Invalid entity_id format: {entity_id}",
            details="Entity ID must start with 'automation.' or 'script.'",
            context={"entity_id": entity_id},
        )
    )
    raise AssertionError("unreachable")


async def _resolve_trace_target(
    client: Any,
    entity_id: str | None,
    domain: Literal["automation", "script"] | None,
    item_id: str | None,
    context_id: str | None,
    run_id: str | None,
) -> tuple[str | None, str, str | None, str | None, ContextTraceMatch | None]:
    """Resolve selectors to entity/domain/item/run and optional context match."""
    _validate_trace_request(entity_id, domain, item_id, context_id, run_id)
    context_match: ContextTraceMatch | None = None
    resolved_run_id = run_id
    resolved_item_id: str | None = item_id
    domain_name: str = domain or "automation"
    if entity_id is not None:
        entity_domain = _entity_domain(entity_id)
        if domain is not None and domain != entity_domain:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "domain does not match entity_id",
                    context={"entity_id": entity_id, "domain": domain},
                )
            )
        domain_name = entity_domain
        object_id = entity_id.split(".", 1)[1]
        resolved_item_id = await _resolve_trace_item_id(client, entity_id, object_id)
        if context_id is not None:
            context_match = await resolve_context_trace(
                client, domain_name, resolved_item_id, context_id
            )
            resolved_run_id = context_match.run_id
    elif context_id is not None and resolved_item_id is not None:
        context_match = await resolve_context_trace(
            client, domain_name, resolved_item_id, context_id
        )
        resolved_run_id = context_match.run_id
    elif context_id is not None:
        context_match = await resolve_global_context(client, context_id, domain)
        domain_name = context_match.domain
        resolved_item_id = context_match.item_id
        resolved_run_id = context_match.run_id
    return entity_id, domain_name, resolved_item_id, resolved_run_id, context_match


class LegacyTraceImplementation:
    """Trace retrieval tools for Home Assistant."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def get_traces(self, **arguments: Any) -> dict[str, Any]:
        entity_id = arguments["entity_id"]
        domain = arguments["domain"]
        item_id = arguments["item_id"]
        context_id = arguments["context_id"]
        run_id = arguments["run_id"]
        limit = arguments["limit"]
        detailed = arguments["detailed"]
        sections = arguments["sections"]
        offset = arguments["offset"]
        order = arguments["order"]
        ctx = arguments["ctx"]
        try:
            if run_id is not None and context_id is not None:
                raise_tool_error(
                    create_error_response(
                        ErrorCode.VALIDATION_INVALID_PARAMETER,
                        "run_id and context_id are mutually exclusive",
                        context={"run_id": run_id, "context_id": context_id},
                        suggestions=[
                            "Pass run_id to fetch a specific stored trace",
                            "Pass context_id to resolve the trace for a context",
                        ],
                    )
                )

            logger.debug(
                f"ha_get_automation_traces starting: id={entity_id or '<domain>'} "
                f"run_id={run_id or '<list>'} context_id={context_id or '<none>'}",
            )
            await safe_progress(
                ctx,
                progress=0,
                total=3,
                message="resolving trace target",
            )
            (
                entity_id,
                domain_name,
                item_id,
                resolved_run_id,
                context_match,
            ) = await _resolve_trace_target(
                self._client, entity_id, domain, item_id, context_id, run_id
            )
            if resolved_run_id is None and (_requested_sections(sections) or detailed):
                raise_tool_error(
                    create_error_response(
                        ErrorCode.VALIDATION_INVALID_PARAMETER,
                        "sections and detailed require a resolved run",
                        context={
                            "resolved_run_id": resolved_run_id,
                            "sections": sections,
                            "detailed": detailed,
                        },
                        suggestions=[
                            "Pass run_id to select a specific trace",
                            "Pass context_id to resolve a run",
                            "Omit sections and detailed when listing traces",
                        ],
                    )
                )

            # Every trace command below is a single request/response with no
            # subscription or streaming, so the shared pooled WebSocket owns the
            # connection lifecycle. A connection-shaped failure on the fetch
            # surfaces as CONNECTION_FAILED.

            await safe_progress(
                ctx,
                progress=1,
                total=3,
                message=(f"fetching trace {'detail' if resolved_run_id else 'list'}"),
            )

            if resolved_run_id:
                detail = await self._fetch_trace_detail(
                    domain_name,
                    item_id or "",
                    entity_id,
                    resolved_run_id,
                    detailed=detailed,
                    sections=sections,
                    ctx=ctx,
                    fallback_trace=(
                        context_match.trace_data if context_match is not None else None
                    ),
                )
                if context_match is not None:
                    _add_context_match(detail, context_id, context_match)
                return detail
            result = await self._fetch_trace_list(
                domain_name,
                item_id,
                entity_id,
                limit=limit,
                offset=offset,
                order=order,
                ctx=ctx,
            )
            return result

        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error getting traces for {entity_id}: {e}")
            exception_to_structured_error(
                e,
                context={"entity_id": entity_id},
                suggestions=[
                    "Verify the automation/script entity_id exists",
                    "Check if traces are available (automation must have run recently)",
                    "Ensure Home Assistant connection is working",
                ],
            )
            return (
                None  # exception_to_structured_error always raises; explicit for CodeQL
            )

    async def _fetch_trace_detail(
        self,
        domain: str,
        item_id: str,
        entity_id: str | None,
        run_id: str,
        *,
        detailed: bool,
        sections: str | None,
        ctx: Context | None,
        fallback_trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Retrieve and format a single trace by run_id.

        ``fallback_trace`` is the component's extended trace dict for the
        matched run, already in hand from the context resolution. Use it
        instead of issuing a separate ``trace/get`` read.
        """
        if fallback_trace is not None:
            trace_data = fallback_trace
        else:
            result = await self._client.send_websocket_message(
                {
                    "type": "trace/get",
                    "domain": domain,
                    "item_id": item_id,
                    "run_id": run_id,
                }
            )
            if not result.get("success"):
                _raise_trace_ws_failure(
                    result.get("error", "Failed to retrieve trace"),
                    {
                        "entity_id": entity_id,
                        "domain": domain,
                        "item_id": item_id,
                        "run_id": run_id,
                    },
                )
            trace_data = result.get("result", {})

        requested = _requested_sections(sections)
        logbook: TraceLogbook | None = None
        # An explicit section list decides on its own: detailed=True must not
        # spend a slow recorder query on rows the caller then filters out.
        if "logbook" in requested or (detailed and not requested):
            try:
                logbook = await fetch_trace_logbook(self._client, trace_data)
            except (ToolError, HomeAssistantError) as err:
                # The run's trace is already in hand; a recorder/logbook
                # failure must not discard it.
                message = (
                    extract_tool_error_message(err)
                    if isinstance(err, ToolError)
                    else str(err)
                )
                logbook = TraceLogbook([], None, [f"logbook unavailable: {message}"])
        await safe_progress(ctx, progress=3, total=3, message="formatting trace")
        formatted = _format_detailed_trace(
            entity_id,
            run_id,
            trace_data,
            domain=domain,
            item_id=item_id or None,
            sections=sections,
            logbook=logbook,
        )
        if logbook is not None and logbook.warnings:
            formatted.setdefault("warnings", []).extend(logbook.warnings)
        return formatted

    async def _fetch_trace_list(
        self,
        domain: str,
        item_id: str | None,
        entity_id: str | None,
        *,
        limit: int,
        offset: int,
        order: Literal["newest", "oldest"],
        ctx: Context | None,
    ) -> dict[str, Any]:
        """List recent traces, attaching diagnostics when none are stored."""
        message: dict[str, Any] = {"type": "trace/list", "domain": domain}
        if item_id is not None:
            message["item_id"] = item_id
        result = await self._client.send_websocket_message(message)

        if not result.get("success"):
            _raise_trace_ws_failure(
                result.get("error", "Failed to list traces"),
                {"entity_id": entity_id, "domain": domain, "item_id": item_id},
            )

        traces_data = result.get("result", [])
        list_warnings: list[str] = []
        if not traces_data and item_id is not None and entity_id is None:
            list_warnings.append(
                f"No traces found for {domain}/{item_id}; "
                "the item_id may be incorrect or the automation/script has not run."
            )

        if not traces_data and entity_id is not None:
            await safe_progress(
                ctx,
                progress=2,
                total=3,
                message="no traces; gathering diagnostics",
            )
            diagnostics, diagnostics_warnings = await _gather_diagnostics(
                self._client, entity_id, domain
            )
            list_warnings.extend(diagnostics_warnings)
            await safe_progress(
                ctx, progress=3, total=3, message="diagnostics complete"
            )
            return _format_trace_list(
                entity_id,
                traces_data,
                limit,
                diagnostics,
                domain=domain,
                offset=offset,
                order=order,
                warnings=list_warnings,
            )

        await safe_progress(
            ctx,
            progress=3,
            total=3,
            message=f"listed {len(traces_data)} traces",
        )
        return _format_trace_list(
            entity_id,
            traces_data,
            limit,
            domain=domain,
            offset=offset,
            order=order,
            warnings=list_warnings,
        )


def register_trace_tools(mcp: Any, client: Any, **kwargs: Any) -> None:
    """Register Home Assistant trace debugging tools."""
    register_tool_methods(mcp, TraceTools(client))


def _add_context_match(
    detail: dict[str, Any],
    context_id: str | None,
    match: ContextTraceMatch,
) -> None:
    """Attach the context resolution metadata to a detailed trace."""
    detail["context_id"] = context_id
    detail["context_match"] = match.match
    detail["context_scanned"] = match.scanned
    if match.other_matches:
        detail["context_other_matches"] = list(match.other_matches)


async def _resolve_trace_item_id(
    client: Any, entity_id: str, fallback_object_id: str
) -> str:
    """
    Resolve entity_id to the unique_id used for trace storage.

    Home Assistant stores traces using the automation/script's unique_id,
    not the entity_id. This function looks up the unique_id from the
    entity registry and falls back to object_id if not found.

    Args:
        client: Pooled REST client exposing ``send_websocket_message``
        entity_id: Full entity_id (e.g., 'automation.morning_routine')
        fallback_object_id: Object ID to use if unique_id lookup fails

    Returns:
        The unique_id for trace lookup, or fallback_object_id
    """
    try:
        # Query entity registry to get unique_id. Best-effort: the pooled client
        # collapses a failure into ``{"success": False, ...}`` (or, for a
        # programming bug, raises) — either way we fall back to object_id and let
        # the subsequent trace fetch surface the real error.
        result = await client.send_websocket_message(
            {"type": "config/entity_registry/get", "entity_id": entity_id}
        )

        if result.get("success") and result.get("result"):
            unique_id = result["result"].get("unique_id")
            if unique_id:
                logger.debug(f"Resolved {entity_id} to unique_id: {unique_id}")
                return str(unique_id)

        # Fallback to object_id if no unique_id found
        logger.debug(
            f"No unique_id found for {entity_id}, using object_id: {fallback_object_id}"
        )
        return fallback_object_id

    except Exception as e:  # noqa: BLE001
        # On any error, fall back to object_id
        logger.warning(
            f"Failed to resolve unique_id for {entity_id}: {e}, "
            f"using object_id: {fallback_object_id}"
        )
        return fallback_object_id


class TraceTools(TraceFacade):
    def __init__(self, client: Any) -> None:
        self.implementation = LegacyTraceImplementation(client)
        super().__init__(self.implementation.get_traces)

    ha_get_automation_traces = tool(
        name="ha_get_automation_traces",
        tags={"History & Statistics"},
        annotations=read_only_hints("Get Automation Traces", open_world=False),
    )(log_tool_usage(legacy_errors(TraceFacade.ha_get_automation_traces)))
