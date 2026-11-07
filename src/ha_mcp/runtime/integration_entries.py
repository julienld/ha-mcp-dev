"""Shared integration inspection with finite metadata, flow and diagnostics ports."""

import logging
from typing import Any

from ha_mcp.errors import HomeAssistantAPIError
from ha_mcp.runtime.errors import raise_classified as exception_to_structured_error
from ha_mcp.runtime.ignored_entries import normalize_ignored_entry
from ha_mcp.runtime.integration_components import (
    SCRUB_DEGRADED_WARNING,
    ComponentEntries,
    _split_component_entry_row,
    fetch_config_entries,
)
from ha_mcp.runtime.integration_schema import (
    fetch_config_subentry_schema,
    fetch_options_schema,
    options_unread_warning,
    options_withheld_warning,
    withhold_component_options,
)
from ha_mcp.tool_api import ToolFailure as ToolError

from .errors import websocket_error_message
from .flows.settings import redaction_enabled
from .integration_inspection import IntegrationInspection
from .integration_logs import get_logger_levels

logger = logging.getLogger(__name__)


class IntegrationEntryReads(IntegrationInspection):
    async def _get_single_entry(
        self,
        entry_id: str,
        include_schema: bool | None,
        *,
        include_subentries: bool,
        include_subentry_schema: bool,
        subentry_type: str | None,
        subentry_id: str | None,
        show_advanced_options: bool,
    ) -> dict[str, Any]:
        """Fetch a single config entry by ID, optionally including its options schema."""
        try:
            read = await fetch_config_entries(self._flow_client(), entry_id=entry_id)
            if read is not None:
                return await self._single_entry_from_component(
                    entry_id,
                    read,
                    include_schema,
                    include_subentries=include_subentries,
                    include_subentry_schema=include_subentry_schema,
                    subentry_type=subentry_type,
                    subentry_id=subentry_id,
                    show_advanced_options=show_advanced_options,
                )

            result = await self._flow_client().get_config_entry(entry_id)
            entry_domain = result.get("domain") if isinstance(result, dict) else None
            if isinstance(result, dict):
                normalize_ignored_entry(result)

            # Core's entry fragment has no `options`, and only the entry's
            # options flow form shows them. With include_schema,
            # `fetch_options_schema` below fills them from that form.
            options_warnings: list[str] = []
            self._note_unread_legacy_options(
                result, entry_id, include_schema, options_warnings
            )

            resp: dict[str, Any] = {
                "success": True,
                "entry_id": entry_id,
                "entry": result,
            }
            if options_warnings:
                resp["warnings"] = options_warnings

            # Surface the effective Python logger level for this integration
            # so users can confirm log level changes took effect.
            # Emit unconditionally for symmetry with the list path (_format_entry).
            level_warnings: list[str] = []
            logger_levels = await get_logger_levels(self._flow_client(), level_warnings)
            level_info = logger_levels.get(entry_domain or "")
            # UNKNOWN, not DEFAULT: an unreadable level is not evidence that the
            # integration runs at the default one (#1947).
            resp["log_level"] = (
                "UNKNOWN"
                if level_warnings
                else (level_info["name"] if level_info else "DEFAULT")
            )
            resp["log_level_raw"] = level_info["raw"] if level_info else None
            if level_warnings:
                resp.setdefault("warnings", []).extend(level_warnings)

            # Describe the options flow's first step: started and aborted.
            if include_schema and result.get("supports_options"):
                await fetch_options_schema(self._flow_client(), entry_id, resp)

            if include_subentries:
                subentries = await self._fetch_config_subentries(entry_id)
                resp["subentry_count"] = len(subentries)
                resp["subentries"] = subentries

            if include_subentry_schema:
                await fetch_config_subentry_schema(
                    self._flow_client(),
                    entry_id,
                    resp,
                    subentry_type=subentry_type,
                    subentry_id=subentry_id,
                    show_advanced_options=show_advanced_options,
                )

            return resp
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            exception_to_structured_error(
                e,
                context={"entry_id": entry_id},
                suggestions=[
                    "Use ha_get_integration() without entry_id to see all "
                    "config entries",
                ],
            )
            return None  # unreachable: exception_to_structured_error raises

    async def _single_entry_from_component(
        self,
        entry_id: str,
        read: ComponentEntries,
        include_schema: bool | None,
        *,
        include_subentries: bool,
        include_subentry_schema: bool,
        subentry_type: str | None,
        subentry_id: str | None,
        show_advanced_options: bool,
    ) -> dict[str, Any]:
        """Build the single-entry response from a component ``config_entries`` read.

        The component row already carries the entry identity, its raw persisted
        ``options`` (secret-scrubbed), and its ``subentries`` identity rows — so
        this one read replaces the legacy ``get_config_entry`` read + OptionsFlow
        start/abort probe + subentries WS call. The options schema (and the
        subentry schema) still come from the legacy live flow: a schema only
        exists inside an open flow, which the component cannot serialize. When a
        schema is requested the component's ``options`` are kept
        (``populate_options=False``) rather than overwritten by the
        OptionsFlow-derived suggested-value shape.

        ``log_level`` / ``log_level_raw`` come from ``get_logger_levels`` on both
        paths (the component does not carry logger overrides).
        """
        if not read.rows:
            # ``async_get_entry(entry_id)`` found nothing — an authoritative
            # not-found, mapped to the same 404 get_config_entry raises.
            raise HomeAssistantAPIError(
                f"Config entry not found: {entry_id}", status_code=404
            )
        entry, subentries = _split_component_entry_row(read.rows[0])
        entry.setdefault("options", {})
        normalize_ignored_entry(entry)

        resp: dict[str, Any] = {
            "success": True,
            "entry_id": entry_id,
            "entry": entry,
        }
        if read.secret_scrub_degraded:
            resp["warnings"] = [SCRUB_DEGRADED_WARNING]

        # Surface the effective Python logger level for this integration
        # (unconditionally, for symmetry with the legacy path and _format_entry).
        level_warnings: list[str] = []
        logger_levels = await get_logger_levels(self._flow_client(), level_warnings)
        level_info = logger_levels.get(entry.get("domain") or "")
        # UNKNOWN, not DEFAULT — see the legacy path in _get_single_entry.
        resp["log_level"] = (
            "UNKNOWN"
            if level_warnings
            else (level_info["name"] if level_info else "DEFAULT")
        )
        resp["log_level_raw"] = level_info["raw"] if level_info else None
        if level_warnings:
            resp.setdefault("warnings", []).extend(level_warnings)

        # Component options are raw persisted values — under redact_secrets
        # they must be redacted on EVERY read (#2157). A read that asks for
        # the options form redacts by that form in fetch_options_schema
        # below, which opens the flow once; any other read opens no flow and
        # withholds every value (#2987).
        schema_read = bool(include_schema and entry.get("supports_options"))
        if (
            redaction_enabled()
            and not schema_read
            and withhold_component_options(entry)
        ):
            resp.setdefault("warnings", []).append(options_withheld_warning(entry_id))

        # Options schema only exists in a live options flow — read it from the
        # legacy flow, but keep the component-provided options (populate_options
        # False) so the raw persisted values win over the flow-derived shape.
        if schema_read:
            await fetch_options_schema(
                self._flow_client(),
                entry_id,
                resp,
                populate_options=False,
            )

        if include_subentries:
            resp["subentry_count"] = len(subentries)
            resp["subentries"] = subentries

        if include_subentry_schema:
            await fetch_config_subentry_schema(
                self._flow_client(),
                entry_id,
                resp,
                subentry_type=subentry_type,
                subentry_id=subentry_id,
                show_advanced_options=show_advanced_options,
            )

        return resp

    async def _attach_knx_project(self, resp: dict[str, Any], entry_id: str) -> None:
        """Attach the parsed KNX ETS project to a single-entry response.

        Reads ``knx/get_knx_project`` (the same command the KNX panel uses) and
        attaches the group-address table, group-range hierarchy, and project
        metadata under ``resp["knx_project"]``. The KNX integration exposes one
        project globally, so the command takes no entry scope; this is gated on
        the entry actually being a KNX integration to avoid attaching unrelated
        data to a non-KNX entry.

        Failures are surfaced as warnings rather than raised — the primary
        entry read already succeeded, mirroring how diagnostics fetch failures
        are handled. The "KNX integration not loaded" case collapses into
        ha_get_integration's existing no-such-entry handling (no KNX entry → no
        entry_id to pass here), so it needs no special casing.
        """
        entry = resp.get("entry") if isinstance(resp.get("entry"), dict) else {}
        domain = entry.get("domain") if isinstance(entry, dict) else None
        if domain != "knx":
            resp.setdefault("warnings", []).append(
                f"include_knx_project ignored: entry {entry_id} is not a KNX "
                f"integration (domain={domain!r})"
            )
            return

        result = await self.backend.execute(
            "integrations.knx_project", {}, self.context
        )
        if not isinstance(result, dict) or not result.get("success"):
            error_msg = websocket_error_message(
                result.get("error", "Unknown error")
                if isinstance(result, dict)
                else result
            )
            resp.setdefault("warnings", []).append(
                f"Failed to fetch KNX project: {error_msg}"
            )
            return

        project = result.get("result")
        if not project:
            # No ETS project uploaded yet — get_knxproject() returns None.
            resp["knx_project"] = {
                "count": 0,
                "group_addresses": {},
                "group_ranges": {},
                "info": {},
                "note": (
                    "The KNX integration is loaded but no ETS project has been "
                    "uploaded yet. Upload a .knxproj file via the KNX panel to "
                    "populate the group-address table."
                ),
            }
            return

        group_addresses = project.get("group_addresses", {})
        resp["knx_project"] = {
            "count": len(group_addresses),
            "group_addresses": group_addresses,
            "group_ranges": project.get("group_ranges", {}),
            "info": project.get("info", {}),
        }

    @staticmethod
    def _note_unread_legacy_options(
        result: Any,
        entry_id: str,
        include_schema: bool | None,
        warnings: list[str],
    ) -> None:
        """Warn that a legacy REST entry's ``options`` were not read (#2987).

        Opening the options flow runs the integration's own code, so a read
        does it only for ``include_schema``, which asks for the flow's form
        and fills ``options`` from it. An entry without an options flow gets
        an empty ``options``: Core's fragment has none.
        """
        if not isinstance(result, dict):
            return
        if not result.get("supports_options"):
            result.setdefault("options", {})
        elif not include_schema:
            warnings.append(options_unread_warning(entry_id))
