"""Shared integration inspection with finite metadata, flow and diagnostics ports."""

import logging
from typing import Any

from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.runtime.errors import raise_failure as raise_tool_error
from ha_mcp.runtime.ignored_entries import normalize_ignored_entry
from ha_mcp.runtime.integration_components import (
    SCRUB_DEGRADED_WARNING,
    fetch_config_entries,
)
from ha_mcp.runtime.integration_schema import (
    entry_count,
    options_unread_warning,
    options_withheld_warning,
    withhold_component_options,
)
from ha_mcp.runtime.validation import validate_identifier_not_empty

from .flows.settings import redaction_enabled
from .integration_entries import IntegrationEntryReads
from .integration_logs import get_logger_levels
from .projection import build_pagination_metadata

logger = logging.getLogger(__name__)


class IntegrationListReads(IntegrationEntryReads):
    async def _list_entries(
        self,
        domain: str | None,
        query: str | None,
        include_opts: bool | None,
        exact_match: bool | None,
        limit_int: int,
        offset_int: int,
        integration_type: str | None = None,
    ) -> dict[str, Any]:
        """List config entries with optional domain/query filtering and pagination."""
        # Component fast path: one in-process read (domain filtered server-side,
        # options materialized on each row) replaces the per-entry OptionsFlow
        # probes; the REST list is read for integration_type only when the
        # component cannot filter by type.
        # Normalize the domain to HA's canonical lowercase: both the component
        # and Core's REST list filter by exact match.
        domain_norm = domain.strip().lower() if domain else None
        params: dict[str, str] = {}
        if domain_norm:
            params["domain"] = domain_norm
        if integration_type is not None:
            # A blank type matches no integration, so the list would come back
            # empty but for entries whose integration Core cannot find.
            params["type"] = validate_identifier_not_empty(
                integration_type, "integration_type"
            )
        read = await fetch_config_entries(
            self._flow_client(), domain=domain_norm, integration_type=params.get("type")
        )
        if read is not None:
            rows = read.rows
            if integration_type is not None and not read.type_filtered:
                # A component without the type filter: Core's REST list
                # decides which entries match the type.
                matching = {
                    entry.get("entry_id")
                    for entry in await self._fetch_rest_entries(params)
                }
                rows = [row for row in rows if row.get("entry_id") in matching]
            listed = await self._list_entries_from_component(
                rows,
                domain_norm,
                query,
                include_opts,
                exact_match,
                limit_int,
                offset_int,
            )
            if include_opts and read.secret_scrub_degraded:
                listed.setdefault("warnings", []).append(SCRUB_DEGRADED_WARNING)
            return listed

        response = await self._fetch_rest_entries(params)

        # Fetch current logger levels once; enrich each entry with its effective level.
        level_warnings: list[str] = []
        logger_levels = await get_logger_levels(self._flow_client(), level_warnings)

        formatted_entries = [
            self._format_entry(entry, include_opts, logger_levels, bool(level_warnings))
            for entry in response
        ]
        result = self._finalize_entry_list(
            formatted_entries,
            domain_norm,
            query,
            exact_match,
            limit_int,
            offset_int,
            level_warnings,
        )
        # Core's rows have no options, and a list opens no options flow to
        # read them (#2987): an entry that has one comes back without the key.
        if include_opts:
            unread = [e for e in result["entries"] if e.get("supports_options")]
            for entry in unread:
                entry.pop("options", None)
            if unread:
                result.setdefault("warnings", []).append(
                    options_unread_warning(entry_count(len(unread)))
                )
        return result

    async def _list_entries_from_component(
        self,
        rows: list[dict[str, Any]],
        domain: str | None,
        query: str | None,
        include_opts: bool | None,
        exact_match: bool | None,
        limit_int: int,
        offset_int: int,
    ) -> dict[str, Any]:
        """List config entries from a component ``config_entries`` read.

        The component already filtered by ``domain`` (server-side) and
        materialized each entry's ``options`` on the row, so the read itself
        needs no per-entry OptionsFlow probe. ``options`` are raw persisted
        values (a field never set may be absent) and may contain
        ``"**redacted**"`` markers.
        With ``redact_secrets`` on, every option value of a returned entry
        that has an options flow is withheld: only that flow's form tells
        the password fields apart, and a list opens no flow (#2987).
        """
        level_warnings: list[str] = []
        logger_levels = await get_logger_levels(self._flow_client(), level_warnings)
        formatted_entries = [
            self._format_entry(row, include_opts, logger_levels, bool(level_warnings))
            for row in rows
        ]
        result = self._finalize_entry_list(
            formatted_entries,
            domain,
            query,
            exact_match,
            limit_int,
            offset_int,
            level_warnings,
        )
        # Component options are raw persisted values — under redact_secrets
        # every RETURNED row must be redacted (#2157).
        if include_opts and redaction_enabled():
            withheld = 0
            for formatted in result["entries"]:
                if withhold_component_options(formatted):
                    withheld += 1
            if withheld:
                result.setdefault("warnings", []).append(
                    options_withheld_warning(entry_count(withheld))
                )
        return result

    def _finalize_entry_list(
        self,
        formatted_entries: list[dict[str, Any]],
        domain: str | None,
        query: str | None,
        exact_match: bool | None,
        limit_int: int,
        offset_int: int,
        extra_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Query-filter, summarize, and paginate formatted entries.

        Shared tail of the component-served and legacy list paths so their
        response shapes stay identical.
        """
        # Apply search filter if query provided
        if query and query.strip():
            formatted_entries = self._filter_by_query(
                formatted_entries, query, exact_match
            )

        # Group by state for summary (computed before pagination for full picture)
        state_summary: dict[str, int] = {}
        for entry in formatted_entries:
            state = entry.get("state", "unknown")
            state_summary[state] = state_summary.get(state, 0) + 1

        # Apply pagination
        total_entries = len(formatted_entries)
        paginated_entries = formatted_entries[offset_int : offset_int + limit_int]

        result_data: dict[str, Any] = {
            "success": True,
            **build_pagination_metadata(
                total_entries, offset_int, limit_int, len(paginated_entries)
            ),
            "entries": paginated_entries,
            "state_summary": state_summary,
            "query": query if query else None,
        }
        if domain:
            result_data["domain_filter"] = domain
        if extra_warnings:
            result_data.setdefault("warnings", []).extend(extra_warnings)
        return result_data

    @staticmethod
    def _format_entry(
        entry: dict[str, Any],
        include_opts: bool | None,
        logger_levels: dict[str, dict[str, Any]] | None = None,
        levels_unknown: bool = False,
    ) -> dict[str, Any]:
        """Copy the entry row minus ``options``/``subentries``; add the tool's fields.

        Every other key passes through (Core's fields, plus ``unique_id`` on the
        component path); ``supports_options`` and ``supports_reconfigure`` are
        forced off for an ignored entry.
        ``options`` comes back when ``include_opts`` is set.
        """
        formatted_entry: dict[str, Any] = {
            key: value
            for key, value in entry.items()
            if key not in ("options", "subentries")
        }
        normalize_ignored_entry(formatted_entry)

        # Surface the effective Python logger level for this integration
        # ("DEFAULT" = no override; falls back to the root logger level).
        # `log_level_raw` is the original numeric level (None when no override
        # exists or HA returned a string instead of an int).
        if logger_levels is not None:
            domain = entry.get("domain") or ""
            level_info = logger_levels.get(domain)
            # UNKNOWN, not DEFAULT: an unreadable level is not evidence that the
            # integration runs at the default one (#1947).
            formatted_entry["log_level"] = (
                "UNKNOWN"
                if levels_unknown
                else (level_info["name"] if level_info else "DEFAULT")
            )
            formatted_entry["log_level_raw"] = level_info["raw"] if level_info else None

        # Include options when requested (for auditing template definitions, etc.)
        if include_opts:
            formatted_entry["options"] = entry.get("options", {})

        return formatted_entry

    @staticmethod
    def _filter_by_query(
        entries: list[dict[str, Any]], query: str, exact_match: bool | None
    ) -> list[dict[str, Any]]:
        """Filter formatted entries by query string with exact or fuzzy matching."""
        matches: list[tuple[int, dict[str, Any]]] = []
        query_lower = query.strip().lower()

        for entry in entries:
            domain_lower = (entry.get("domain") or "").lower()
            title_lower = (entry.get("title") or "").lower()

            # Check for exact substring matches first (highest priority)
            if query_lower in domain_lower or query_lower in title_lower:
                matches.append((100, entry))
            elif not exact_match:
                # Fuzzy matching only when exact_match is disabled
                from ha_mcp.utils.fuzzy_search import calculate_ratio

                domain_score = calculate_ratio(query_lower, domain_lower)
                title_score = calculate_ratio(query_lower, title_lower)
                best_score = max(domain_score, title_score)

                if best_score >= 70:  # threshold for fuzzy matches
                    matches.append((best_score, entry))

        # Sort by score descending
        matches.sort(key=lambda x: x[0], reverse=True)
        return [match[1] for match in matches]

    async def _fetch_rest_entries(self, params: dict[str, str]) -> list[Any]:
        """Core's REST entry list, filtered by Core with ``params``."""
        response = await self._flow_client().list_config_entries(**params)
        if not isinstance(response, list):
            raise_tool_error(
                create_error_response(
                    ErrorCode.SERVICE_CALL_FAILED,
                    "Unexpected response format from Home Assistant",
                    context={"response_type": type(response).__name__},
                )
            )
        return response
