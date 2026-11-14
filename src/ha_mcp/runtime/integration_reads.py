"""Shared integration discovery, schema and optional-detail request routing."""

import logging
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import Field

from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.runtime.errors import raise_classified as exception_to_structured_error
from ha_mcp.runtime.errors import raise_failure as raise_tool_error
from ha_mcp.runtime.integration_ws_commands import attach_ws_commands
from ha_mcp.runtime.validation import validate_identifier_not_empty
from ha_mcp.tool_api import ToolFailure as ToolError
from ha_mcp.tools.coercion import JSON_STRING_COERCION

from .diagnostics import fetch_integration_diagnostics, parse_diagnostics_fields
from .flows.settings import backend_flow_settings
from .integration_list import IntegrationListReads

logger = logging.getLogger(__name__)


def inspection_starts_flow(
    arguments: dict[str, Any], *, redact: Callable[[], bool] | None = None
) -> bool:
    """Effects follow validated routing; opening an arbitrary Core flow can write."""
    detail = arguments.get("entry_id") is not None
    return bool(
        detail
        and (
            arguments.get("include_schema") or arguments.get("include_subentry_schema")
        )
    )


class IntegrationReadTools(IntegrationListReads):
    async def ha_get_integration(
        self,
        entry_id: Annotated[
            str | None,
            Field(
                description="Config entry ID to get details for.",
                default=None,
            ),
        ] = None,
        query: Annotated[
            str | None,
            Field(
                description="When listing, search by domain or title.",
                default=None,
            ),
        ] = None,
        domain: Annotated[
            str | None,
            Field(
                description="Filter by integration domain (e.g. 'template', 'group'). "
                "When set, includes the full options/configuration for each entry.",
                default=None,
            ),
        ] = None,
        integration_type: Annotated[
            str | None,
            Field(
                description="When listing, keep only entries whose integration "
                "has this type, matched by Home Assistant itself (the manifest's "
                "integration_type, e.g. 'device', 'hub', 'service', 'helper'). "
                "Home Assistant does not reject an unknown type: for any type but "
                "'helper' it also keeps entries whose integration it cannot find "
                "(e.g. a removed custom integration), so an unknown type returns "
                "only those.",
                default=None,
            ),
        ] = None,
        include_options: Annotated[
            bool,
            Field(
                description="Include the options object for each entry. "
                "Automatically enabled when domain filter is set. "
                "For UI-created flow-based helpers (template, group, "
                "utility_meter, derivative, ...), the current config — "
                "template body, group members, source entity, etc. — is "
                "here. Read through the ha_mcp_tools custom component; without "
                "it an entry that has an options flow comes back without options "
                "and a warning, and only include_schema on that entry reads them. "
                "With the component, prefer this over include_schema when you "
                "only need the current values; use include_schema when you also "
                "need the field types or selector metadata.",
                default=False,
            ),
        ] = False,
        include_schema: Annotated[
            bool,
            Field(
                description="When entry_id is set, also describe the options flow "
                "form as options_schema.fields: each field's type, current value "
                "and Home Assistant's help text. A flow that opens with a menu "
                "lists menu_options instead (ha_set_integration(entry_id=..., "
                "menu_choice=...) opens one), and a flow Home "
                "Assistant aborts gives aborted, plus reason_text when Home "
                "Assistant has a string for the reason. Only applies "
                "when supports_options=true. The flow is started, described "
                "and aborted; starting it runs the integration's own flow code, "
                "and some integrations act there (Sonoff LAN signs in to its "
                "cloud). For an integration's setup form, use "
                "ha_set_integration(domain=...).",
                default=False,
            ),
        ] = False,
        include_subentries: Annotated[
            bool,
            Field(
                description=(
                    "When entry_id is set, include config subentries for the integration "
                    "entry."
                ),
                default=False,
            ),
        ] = False,
        include_subentry_schema: Annotated[
            bool,
            Field(
                description=(
                    "When entry_id is set, describe a config subentry flow's "
                    "form as subentry_schema.fields (same shape as "
                    "include_schema); the flow is aborted afterwards. Pair with "
                    "subentry_type, and optionally subentry_id for the "
                    "reconfigure form."
                ),
                default=False,
            ),
        ] = False,
        subentry_type: Annotated[
            str | None,
            Field(
                description=(
                    "Integration-defined subentry type used with "
                    "include_subentry_schema=True."
                ),
                default=None,
            ),
        ] = None,
        subentry_id: Annotated[
            str | None,
            Field(
                description=(
                    "Existing subentry ID used with include_subentry_schema=True "
                    "to inspect a reconfigure flow."
                ),
                default=None,
            ),
        ] = None,
        show_advanced_options: Annotated[
            bool,
            Field(
                description=(
                    "When include_subentry_schema=True, ask older Home Assistant "
                    "versions to expose advanced flow options. No-op on HA "
                    "2026.6+; pending removal before HA 2027.6."
                ),
                default=False,
            ),
        ] = False,
        exact_match: Annotated[
            bool,
            Field(
                description=(
                    "Use exact substring matching for query filter. Set to False for fuzzy "
                    "matching when the query may contain typos."
                ),
                default=True,
            ),
        ] = True,
        limit: Annotated[
            int,
            Field(
                default=50,
                ge=1,
                le=200,
                description="Max entries to return per page in list mode",
            ),
        ] = 50,
        offset: Annotated[
            int,
            Field(
                default=0,
                ge=0,
                description="Number of entries to skip for pagination",
            ),
        ] = 0,
        include_diagnostics: Annotated[
            bool,
            Field(
                description=(
                    "When entry_id is set, also fetch the integration's diagnostics dump — "
                    "integration-defined JSON (commonly includes redacted config, device "
                    "list, state snapshots; exact top-level keys vary by integration), the "
                    "same artifact as the UI's 'Download diagnostics'. Payloads can be "
                    "large (Hue ~290 KB, ZHA/MQTT/ESPHome several MB) — pair with "
                    "diagnostics_fields or diagnostics_truncate_at_bytes."
                ),
                default=False,
            ),
        ] = False,
        include_ws_commands: Annotated[
            bool,
            Field(
                description=(
                    "When entry_id is set, also list the integration's own "
                    "'<domain>/' WebSocket commands (the API its panel uses, e.g. "
                    "KNX's knx/get_knx_project) under ws_commands, each with the "
                    "request schema Home Assistant registered for it. Send one "
                    "with ha_set_integration(entry_id=..., ws_command=...). "
                    "Needs the ha_mcp_tools custom component; without it a "
                    "warning says the list is unavailable."
                ),
                default=False,
            ),
        ] = False,
        device_id: Annotated[
            str | None,
            Field(
                description=(
                    "With include_diagnostics=True, return the device-scoped diagnostics "
                    "dump for this device instead of the full integration dump. Some "
                    "integrations only expose config-entry-level dumps."
                ),
                default=None,
            ),
        ] = None,
        diagnostics_fields: Annotated[
            list[str] | str | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Top-level keys to keep from the diagnostics data payload (e.g. "
                    "['home_assistant', 'issues']). Accepts a JSON list or comma-separated "
                    "string. Only applies when include_diagnostics=True and the data "
                    "payload is a dict. Unknown keys are dropped and listed under "
                    "omitted_fields."
                ),
                default=None,
            ),
        ] = None,
        diagnostics_truncate_at_bytes: Annotated[
            int | None,
            Field(
                description=(
                    "Byte cap on the serialized diagnostics payload (after "
                    "diagnostics_fields and diagnostics_data_path have been applied). On "
                    "hit, drops data and emits truncated=true, bytes_total, byte_cap, plus "
                    "available_fields (when the capped value is a dict). Recommended "
                    "starting point: 20000 bytes. Only applies when "
                    "include_diagnostics=True."
                ),
                default=None,
                ge=1,
            ),
        ] = None,
        diagnostics_data_path: Annotated[
            str | None,
            Field(
                description=(
                    "Dotted path into the diagnostics data sub-tree (e.g. '<list-valued "
                    "path>' for per-device records, 'home_assistant.version' for HA core "
                    "version; the exact key path varies by integration version). Walks into"
                    " the post-fields payload. Resolution failures replace data with null "
                    "and surface data_path_error. Only applies when "
                    "include_diagnostics=True."
                ),
                default=None,
            ),
        ] = None,
        diagnostics_data_offset: Annotated[
            int | None,
            Field(
                description=(
                    "Pagination start index for list-valued diagnostics_data_path results. "
                    "Ignored when diagnostics_data_path is unset, diagnostics_data_limit is"
                    " unset, or the resolved value is not a list. Only applies when "
                    "include_diagnostics=True."
                ),
                default=0,
                ge=0,
            ),
        ] = 0,
        diagnostics_data_limit: Annotated[
            int | None,
            Field(
                description=(
                    "Pagination window size for list-valued diagnostics_data_path results. "
                    "When set with a list-resolved path, swaps data for a pagination "
                    "envelope {path, items, offset, limit, total, has_more}. Default None "
                    "returns the full resolved value. Only applies when "
                    "include_diagnostics=True."
                ),
                default=None,
                ge=1,
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Get integration (config entry) information with pagination.

        Without an entry_id: Lists all configured integrations with optional filters.
        With an entry_id: Returns detailed information including full options/configuration.

        WHEN NOT TO USE:
        - Changing an entry, or describing a setup form or a form behind a
          menu: use ha_set_integration (without config it returns the form).

        EXAMPLES:
        - List / search: ha_get_integration(query="zigbee")
        - Get an entry with its editable fields: ha_get_integration(entry_id="abc123", include_schema=True)
        - Diagnostics dump, paged along a list-valued path: ha_get_integration(entry_id="abc123", include_diagnostics=True, diagnostics_data_path="<list-valued path>", diagnostics_data_limit=10, diagnostics_data_offset=20)
        - Inspect a subentry reconfigure schema: ha_get_integration(entry_id="abc123", include_subentry_schema=True, subentry_type="conversation", subentry_id="sub123")
        - Options flow that opens with a menu: ha_get_integration(entry_id="abc123", include_schema=True) lists menu_options; ha_set_integration(entry_id="abc123", menu_choice="<option>") opens that form
        - List template entries with their options: ha_get_integration(domain="template")
        - Only service integrations: ha_get_integration(integration_type="service")
        - An entry's panel commands: ha_get_integration(entry_id="abc123", include_ws_commands=True)

        OPTIONS: with the component, ``options`` are the stored mapping as-is,
        so a field never set may be absent and a section's fields stay nested
        under the section key (e.g. a template helper's ``additional_options``);
        values that match a ``secrets.yaml`` entry are returned as
        ``"**redacted**"``. Without it, include_schema=True reads ``options``
        from the options form: unset fields at their schema default, a
        section's fields at the top level. With redact_secrets on, every
        option value of an entry that has an options flow is redacted unless
        include_schema=True reads the form that names the password fields;
        an entry without an options flow has no such form, so its option
        values come back as stored.

        Each entry carries ``log_level``: the canonical Python logger level name
        (``DEBUG``/``INFO``/``WARNING``/``ERROR``/``CRITICAL``) when the
        integration has a log-level override (set one with
        ``ha_set_integration(log_level=...)``), or ``"DEFAULT"``
        (uppercase sentinel) when no override is set; and ``log_level_raw``: the
        original numeric level (e.g. ``10`` for DEBUG) when HA returned an int,
        ``None`` otherwise. This is distinct from the app side, where
        ``ha_get_app`` returns Supervisor's lowercase ``"default"`` literal — do
        not cross-compare.
        """
        async with backend_flow_settings(self.backend, self.context):
            try:
                include_opts = include_options
                include_schema_bool = include_schema
                include_diagnostics_bool = include_diagnostics
                include_subentries_bool = include_subentries
                include_subentry_schema_bool = include_subentry_schema
                show_advanced_options_bool = show_advanced_options
                exact_match_bool = exact_match
                limit_int = limit
                offset_int = offset
                fields_list = parse_diagnostics_fields(diagnostics_fields)
                truncate_bytes = diagnostics_truncate_at_bytes
                data_offset_int = (
                    diagnostics_data_offset
                    if diagnostics_data_offset is not None
                    else 0
                )
                data_limit_int = diagnostics_data_limit
                # Type-guard ``diagnostics_data_path`` here so a bad caller (dict /
                # list) surfaces as ``VALIDATION_INVALID_PARAMETER`` instead of
                # leaking as ``INTERNAL_ERROR`` from the resolver's ``.strip()``
                # downstream.
                if diagnostics_data_path is not None and not isinstance(
                    diagnostics_data_path, str
                ):
                    raise_tool_error(
                        create_error_response(
                            ErrorCode.VALIDATION_INVALID_PARAMETER,
                            "diagnostics_data_path must be a string, got "
                            f"{type(diagnostics_data_path).__name__}",
                            context={"parameter": "diagnostics_data_path"},
                        )
                    )
                # Auto-enable options when domain filter is set. A blank domain is no
                # filter to Core, so it would list and probe every entry.
                if domain is not None:
                    validate_identifier_not_empty(domain, "domain")
                    include_opts = True

                # If entry_id provided, get specific config entry
                if entry_id is not None:
                    resp = await self._get_entry_detail_response(
                        entry_id,
                        include_schema=include_schema_bool,
                        include_subentries=include_subentries_bool,
                        include_subentry_schema=include_subentry_schema_bool,
                        subentry_type=subentry_type,
                        subentry_id=subentry_id,
                        show_advanced_options=show_advanced_options_bool,
                        include_diagnostics=include_diagnostics_bool,
                        include_ws_commands=include_ws_commands,
                        device_id=device_id,
                        fields_list=fields_list,
                        truncate_bytes=truncate_bytes,
                        diagnostics_data_path=diagnostics_data_path,
                        data_offset_int=data_offset_int,
                        data_limit_int=data_limit_int,
                    )
                    if integration_type is not None:
                        resp.setdefault("warnings", []).append(
                            "integration_type was ignored: it filters the list "
                            "(no entry_id)"
                        )
                    return resp

                # List mode - get all config entries
                result = await self._list_entries(
                    domain,
                    query,
                    include_opts,
                    exact_match_bool,
                    limit_int,
                    offset_int,
                    integration_type=integration_type,
                )
                ignored_detail_params = self._ignored_diagnostics_detail_params(
                    include_diagnostics=include_diagnostics_bool,
                    include_ws_commands=include_ws_commands,
                    device_id=device_id,
                    fields_list=fields_list,
                    truncate_bytes=truncate_bytes,
                    diagnostics_data_path=diagnostics_data_path,
                    data_offset_int=data_offset_int,
                    data_limit_int=data_limit_int,
                ) + self._ignored_subentry_detail_params(
                    include_subentries=include_subentries_bool,
                    include_subentry_schema=include_subentry_schema_bool,
                    subentry_type=subentry_type,
                    subentry_id=subentry_id,
                    show_advanced_options=show_advanced_options_bool,
                )
                if ignored_detail_params:
                    result.setdefault("warnings", []).append(
                        f"{', '.join(ignored_detail_params)} "
                        "ignored because entry_id was not set (list mode)"
                    )
                if include_schema_bool:
                    result.setdefault("warnings", []).append(
                        "include_schema was ignored: it describes an entry's "
                        "options flow and needs entry_id. For an integration's "
                        "setup form, use ha_set_integration(domain=...)"
                    )
                return result

            except ToolError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to get integrations: {e}")
                exception_to_structured_error(
                    e,
                    suggestions=[
                        "Verify Home Assistant connection is working",
                        "Check that the API is accessible",
                        "Ensure your token has sufficient permissions",
                    ],
                )
                return None  # unreachable: exception_to_structured_error raises

    async def _get_entry_detail_response(
        self,
        entry_id: str,
        *,
        include_schema: bool,
        include_subentries: bool,
        include_subentry_schema: bool,
        subentry_type: str | None,
        subentry_id: str | None,
        show_advanced_options: bool,
        include_diagnostics: bool,
        include_ws_commands: bool,
        device_id: str | None,
        fields_list: list[str] | None,
        truncate_bytes: int | None,
        diagnostics_data_path: str | None,
        data_offset_int: int,
        data_limit_int: int | None,
    ) -> dict[str, Any]:
        """Build the single-entry response, attaching diagnostics/commands when asked."""
        resp = await self._get_single_entry(
            entry_id,
            include_schema,
            include_subentries=include_subentries or include_subentry_schema,
            include_subentry_schema=include_subentry_schema,
            subentry_type=subentry_type,
            subentry_id=subentry_id,
            show_advanced_options=show_advanced_options,
        )
        if include_diagnostics:
            resp["diagnostics"] = await fetch_integration_diagnostics(
                self._flow_client(),
                entry_id,
                device_id,
                fields=fields_list,
                truncate_at_bytes=truncate_bytes,
                data_path=diagnostics_data_path,
                data_offset=data_offset_int,
                data_limit=data_limit_int,
            )
        elif device_id is not None:
            resp.setdefault("warnings", []).append(
                "device_id was provided but ignored because include_diagnostics=False"
            )
        if include_ws_commands:
            await attach_ws_commands(self._flow_client(), resp)
        return resp

    @staticmethod
    def _ignored_diagnostics_detail_params(
        *,
        include_diagnostics: bool,
        include_ws_commands: bool,
        device_id: str | None,
        fields_list: list[str] | None,
        truncate_bytes: int | None,
        diagnostics_data_path: str | None,
        data_offset_int: int,
        data_limit_int: int | None,
    ) -> list[str]:
        """Detail-only diagnostics/command params that are ignored in list mode."""
        ignored_detail_params: list[str] = []
        if include_diagnostics:
            ignored_detail_params.append("include_diagnostics")
        if include_ws_commands:
            ignored_detail_params.append("include_ws_commands")
        if device_id is not None:
            ignored_detail_params.append("device_id")
        if fields_list is not None:
            ignored_detail_params.append("diagnostics_fields")
        if truncate_bytes is not None:
            ignored_detail_params.append("diagnostics_truncate_at_bytes")
        if diagnostics_data_path is not None:
            ignored_detail_params.append("diagnostics_data_path")
        if data_offset_int > 0:
            ignored_detail_params.append("diagnostics_data_offset")
        if data_limit_int is not None:
            ignored_detail_params.append("diagnostics_data_limit")
        return ignored_detail_params

    @staticmethod
    def _ignored_subentry_detail_params(
        *,
        include_subentries: bool,
        include_subentry_schema: bool,
        subentry_type: str | None,
        subentry_id: str | None,
        show_advanced_options: bool,
    ) -> list[str]:
        """Detail-only subentry params that are ignored in list mode."""
        ignored_detail_params: list[str] = []
        if include_subentries:
            ignored_detail_params.append("include_subentries")
        if include_subentry_schema:
            ignored_detail_params.append("include_subentry_schema")
        if subentry_type is not None:
            ignored_detail_params.append("subentry_type")
        if subentry_id is not None:
            ignored_detail_params.append("subentry_id")
        if show_advanced_options:
            ignored_detail_params.append("show_advanced_options")
        return ignored_detail_params
