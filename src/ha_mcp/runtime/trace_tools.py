"""Public trace contract, independent of Core and the MCP SDK."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from pydantic import Field


class TraceFacade:
    def __init__(self, get_traces: Callable[..., Awaitable[dict[str, Any]]]) -> None:
        self.get_traces = get_traces

    async def ha_get_automation_traces(
        self,
        entity_id: Annotated[
            str | None,
            Field(
                description=(
                    "Automation or script entity_id. Omit when resolving a "
                    "context-only lookup."
                ),
                default=None,
            ),
        ] = None,
        domain: Annotated[
            Literal["automation", "script"] | None,
            Field(
                description=(
                    "List recent traces across every automation or script when "
                    "entity_id is omitted. Required with item_id."
                ),
                default=None,
            ),
        ] = None,
        item_id: Annotated[
            str | None,
            Field(
                description=(
                    "Core's trace item id from a list row or context "
                    "resolution. Use with domain and run_id when no entity_id "
                    "is available."
                ),
                default=None,
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            Field(
                description="Specific trace run_id to retrieve detailed trace.",
                default=None,
            ),
        ] = None,
        context_id: Annotated[
            str | None,
            Field(
                description=(
                    "Context id to resolve to its trace. Accepts the trace "
                    "run's own `context.id` or, with the ha_mcp_tools "
                    "component, the context id of the event or service call "
                    "that triggered it. Mutually exclusive with run_id."
                ),
                default=None,
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                description="Maximum number of traces to return when listing (default: 10, max: 50).",
                default=10,
                ge=1,
                le=50,
            ),
        ] = 10,
        detailed: Annotated[
            bool,
            Field(
                description="Include the run's logbook entries in the detail response.",
                default=False,
            ),
        ] = False,
        sections: Annotated[
            str | None,
            Field(
                description=(
                    "Comma-separated top-level keys from Core's extended trace "
                    "dict to return, plus 'logbook' for the run's logbook. "
                    "Available keys depend on the run; examples: 'trace', "
                    "'config', 'context', 'error', 'logbook'. A requested name "
                    "this run lacks is reported in 'warnings'. Omit, or pass an "
                    "empty string, to return Core's full extended dict."
                ),
                default=None,
            ),
        ] = None,
        offset: Annotated[
            int,
            Field(
                description="Number of traces to skip from the start of the requested order. Use with `limit` to page through stored traces when `total_available > limit`.",
                default=0,
                ge=0,
            ),
        ] = 0,
        order: Annotated[
            Literal["newest", "oldest"],
            Field(
                description="Order traces are returned in. 'newest' returns most-recent first; "
                "'oldest' returns chronological-first.",
                default="newest",
            ),
        ] = "newest",
        ctx: Any = None,
    ) -> dict[str, Any]:
        """Get execution traces for automations and scripts to debug issues.

        Traces show what triggered a run, which conditions passed or failed,
        which actions executed, any errors, and variable values during
        execution. Home Assistant keeps only the most recent runs of each
        automation or script (its stored_traces setting), so older runs are
        not available.

        Do not use this tool for general log history or recorder statistics;
        use `ha_get_logs` for logs and `ha_get_history` for history/statistics.

        USAGE MODES:
        1. List recent traces (omit run_id and context_id).
           ha_get_automation_traces("automation.motion_light")
           ha_get_automation_traces(domain="automation")
        2. Get a detailed trace (provide run_id): returns Core's extended trace
           dict unchanged, including config, raw step trace, context, errors
           and variables. Pass `sections` to keep only named top-level keys
           (plus 'logbook' for the run's logbook); a requested name the run
           lacks is reported in `warnings` and the run's own keys are listed.
           An empty `sections` string means omitted.
           ha_get_automation_traces("automation.motion_light", run_id="1705312800.123456")
           ha_get_automation_traces(domain="automation", item_id="uid", run_id="...")
        3. Resolve a trace by context (provide context_id): the response
           selects Core's run for that context and reports `context_match` as
           `trace` or `parent`. With the ha_mcp_tools component,
           `context_other_matches` lists the other runs that matched the
           context id (own or triggering parent); Core's own `trace/contexts`
           keeps one run per context id. A context Core does not hold is
           reported as not found with a hint that the component resolves
           triggering (parent) contexts.
           ha_get_automation_traces(context_id="01J...")

        RESPONSE FIELDS:
        - A detail response is Core's extended `trace/get` dict: `config`,
          `trace`, `context`, `timestamp`, `state`, `error`,
          `script_execution`, `blueprint_inputs` and any run-specific fields.
        - `success`, `run_id`, `domain` and `item_id` identify the run.
          `entity_id` is present when the caller supplied it; a context-only
          lookup returns Core's `domain`/`item_id` instead of inventing one.
        - `context_match` is `trace` or `parent`; `context_scanned` reports
          how many stored runs the ha_mcp_tools component inspected while
          resolving the context id, and is 0 when Core's own-context map
          answered.
        - `logbook_entries`, `logbook_transport`, `logbook_total` and
          `logbook_truncated` describe the run's logbook rows.
        """
        return await self.get_traces(
            entity_id=entity_id,
            domain=domain,
            item_id=item_id,
            context_id=context_id,
            run_id=run_id,
            limit=limit,
            detailed=detailed,
            sections=sections,
            offset=offset,
            order=order,
            ctx=ctx,
        )
