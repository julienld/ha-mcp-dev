"""Core trace projections and selector validation shared by both runtimes."""

from typing import Any, Literal

from ha_mcp.errors import ErrorCode, create_error_response

from .errors import raise_failure as raise_tool_error
from .trace_logbook import TraceLogbook
from .validation import validate_identifier_not_empty


def _validate_trace_request(
    entity_id: str | None,
    domain: Literal["automation", "script"] | None,
    item_id: str | None,
    context_id: str | None,
    run_id: str | None,
) -> None:
    """Validate the selector combination before any trace command."""
    if entity_id is not None:
        validate_identifier_not_empty(
            entity_id,
            "entity_id",
            suggestions=[
                "Pass an automation.* or script.* entity_id",
                "Omit entity_id with domain to list across a domain",
            ],
        )
    if item_id is not None:
        validate_identifier_not_empty(
            item_id,
            "item_id",
            suggestions=[
                "Use Core's item_id from a trace/list row or context resolution",
                "Pass an entity_id instead when you have one",
            ],
        )
        if entity_id is not None:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "entity_id and item_id are mutually exclusive",
                    context={"entity_id": entity_id, "item_id": item_id},
                    suggestions=[
                        "Pass entity_id for a normal automation/script lookup",
                        "Pass domain and item_id for a Core trace key",
                    ],
                )
            )
        if domain is None:
            raise_tool_error(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "domain is required with item_id",
                    context={"item_id": item_id},
                    suggestions=[
                        "Pass domain='automation' or 'script' with item_id",
                    ],
                )
            )
    if context_id is not None:
        validate_identifier_not_empty(
            context_id,
            "context_id",
            suggestions=[
                "Pass the trace's own `context.id` or the triggering "
                + "event/service context id",
                "Omit context_id to list recent traces",
            ],
            context={"entity_id": entity_id},
        )
    if (
        run_id is not None
        and entity_id is None
        and not (domain is not None and item_id is not None)
    ):
        raise_tool_error(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "run_id needs entity_id, or domain with item_id",
                context={"run_id": run_id},
                suggestions=[
                    "Pass the automation/script entity_id with run_id",
                    "Pass domain and Core's item_id from a list row",
                    "Use context_id alone to resolve a run",
                ],
            )
        )
    if entity_id is None and context_id is None and domain is None:
        raise_tool_error(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "Pass entity_id, domain, or context_id",
                suggestions=[
                    "Pass an entity_id for one automation/script",
                    "Pass domain='automation' or 'script' to list across a domain",
                    "Pass context_id to resolve a run without an entity_id",
                ],
            )
        )


def _requested_sections(sections: str | None) -> set[str]:
    """Return the lower-cased section names requested by the caller."""
    requested: set[str] = set()
    if not sections:
        return requested
    for section in sections.split(","):
        normalized = section.strip().lower()
        if normalized:
            requested.add(normalized)
    return requested


def trace_target(automation_id: str) -> tuple[str, str]:
    if automation_id.startswith("automation."):
        domain = "automation"
    elif automation_id.startswith("script."):
        domain = "script"
    else:
        raise_tool_error(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                f"Invalid entity_id format: {automation_id}",
                details="Entity ID must start with 'automation.' or 'script.'",
                context={"automation_id": automation_id},
            )
        )
    return domain, automation_id.split(".", 1)[1]


def _diagnostic_suggestion(diagnostics: dict[str, Any], domain: str) -> str:
    """Describe the first Core-provided reason no trace is available."""
    if not diagnostics.get("entity_exists"):
        return f"Could not find {domain} entity. Verify the entity_id with ha_search()."
    validation = diagnostics.get("validation")
    if isinstance(validation, dict) and validation.get("status") not in {
        None,
        "ok",
    }:
        error = validation.get("error")
        return (
            f"Core reports this {domain} did not load ({validation.get('status')}): "
            f"{error or 'see the repair issue'}"
        )
    if diagnostics.get("trace_storage_enabled") is False:
        return (
            f"Trace storage is disabled for this {domain} (stored_traces: 0); "
            "enable it in the automation/script trace settings."
        )
    if not diagnostics.get("trace_key_available"):
        return (
            "This item has no registry unique_id, so Core has no key under "
            "which to store a trace (common for YAML automations without an id)."
        )
    if diagnostics.get("loaded") is False:
        return (
            "Core reports this automation is not loaded. Check its validation "
            "or repair issue; automation.trigger can still execute a disabled "
            "automation."
        )
    if diagnostics.get("entity_state") == "unavailable":
        return (
            f"The {domain} is unavailable, so Home Assistant cannot run it. "
            "Check the integration that provides it and the Home Assistant logs."
        )
    if domain == "automation" and diagnostics.get("entity_state") == "off":
        return (
            "This automation is disabled (state off). automation.trigger can "
            "still execute it and record a trace."
        )
    return (
        "No stored trace is available yet. Run the automation/script once, "
        "then list traces again."
    )


def _trace_start(trace: dict[str, Any]) -> str:
    """Return Core's start timestamp, the sort key for ``trace/list`` rows."""
    return str(trace["timestamp"]["start"])


def _format_trace_list(
    entity_id: str | None,
    traces: list[dict[str, Any]],
    limit: int,
    diagnostics: dict[str, Any] | None = None,
    *,
    domain: str | None = None,
    offset: int = 0,
    order: Literal["newest", "oldest"] = "newest",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Format trace list for AI consumption.

    Args:
        entity_id: The automation or script entity_id, or None for a domain list
        traces: List of trace data from Home Assistant (sorted here by Core's
            start timestamp before paging)
        limit: Maximum number of traces to include
        diagnostics: Optional diagnostic information when traces are empty
        domain: The requested domain for a domain-wide list
        offset: Number of traces to skip from the start of the requested order
        order: 'newest' (default) returns most-recent first; 'oldest' chronological
    """
    # HA's trace/list returns runs first, then not-triggered traces, so list
    # position is not chronological. Sort by Core's own start timestamp before
    # picking the newest or oldest window.
    ordered = sorted(traces, key=_trace_start)
    if order == "newest":
        end = len(ordered) - offset
        start = max(end - limit, 0)
        window = list(reversed(ordered[start:end])) if end > 0 else []
    else:
        window = ordered[offset : offset + limit]

    # Pass Core's short dict through unchanged instead of projecting a
    # field allowlist; native keys such as script_execution stay as-is.
    formatted_traces = [dict(trace) for trace in window]

    result: dict[str, Any] = {
        "success": True,
        "trace_count": len(formatted_traces),
        "total_available": len(traces),
        "offset": offset,
        "order": order,
        "has_more": offset + len(formatted_traces) < len(traces),
        "traces": formatted_traces,
        "hint": (
            "Use run_id with domain and item_id (or entity_id) to get "
            "detailed trace information"
        ),
    }
    if entity_id is not None:
        result["entity_id"] = entity_id
    if domain is not None:
        result["domain"] = domain

    # Include diagnostics when traces are empty
    if diagnostics is not None and len(traces) == 0:
        result["diagnostics"] = diagnostics

    if warnings:
        result["warnings"] = list(warnings)

    return result


_TRACE_METADATA_KEYS = frozenset(
    {
        "success",
        "run_id",
        "domain",
        "item_id",
        "entity_id",
        "warnings",
        "logbook_entries",
        "logbook_transport",
        "logbook_total",
        "logbook_truncated",
    }
)

# Keys the tool adds around Core's extended dict rather than keys of the run.
# Core's own ``run_id``, ``domain`` and ``item_id`` stay in the run's key list.
_TOOL_ADDED_SECTION_KEYS = _TRACE_METADATA_KEYS - {"run_id", "domain", "item_id"}


def _format_detailed_trace(
    entity_id: str | None,
    run_id: str,
    trace: dict[str, Any],
    *,
    domain: str | None = None,
    item_id: str | None = None,
    sections: str | None = None,
    logbook: TraceLogbook | None = None,
) -> dict[str, Any]:
    """Return Core's extended trace dict with the tool's metadata.

    ``trace`` passes through unchanged unless ``sections`` keeps only the
    named top-level keys; a requested name this run lacks adds a ``warnings``
    line that lists the run's own keys.
    """
    result = dict(trace)
    result["success"] = True
    result["run_id"] = run_id
    if domain is not None:
        result["domain"] = domain
    if item_id is not None:
        result["item_id"] = item_id
    if entity_id is not None:
        result["entity_id"] = entity_id
    if logbook is not None:
        result["logbook_entries"] = logbook.entries
        if logbook.transport is not None:
            result["logbook_transport"] = logbook.transport
        result["logbook_total"] = logbook.total
        result["logbook_truncated"] = logbook.truncated
    if sections:
        result = _filter_trace_sections(result, sections)
    return result


def _filter_trace_sections(result: dict[str, Any], sections: str) -> dict[str, Any]:
    """Keep requested top-level Core keys; warn about names this run lacks."""
    requested = _requested_sections(sections)
    if not requested:
        return result
    # ``logbook`` is the tool's name for the fetched ``logbook_*`` fields, which
    # Core's extended dict does not contain.
    available = set(result)
    if "logbook_entries" in result:
        available.add("logbook")
    missing = sorted(requested - available)
    if missing:
        # The run's own keys, as Core's extended dict names them; the logbook
        # fields are the tool's name for the requested ``logbook`` section.
        run_keys = sorted(set(result) - _TOOL_ADDED_SECTION_KEYS)
        if "logbook_entries" in result:
            run_keys.append("logbook")
        result.setdefault("warnings", []).append(
            "Trace section(s) not in this run: "
            + ", ".join(missing)
            + ". This run has: "
            + ", ".join(run_keys)
        )
    keep = requested | _TRACE_METADATA_KEYS
    return {key: value for key, value in result.items() if key in keep}
