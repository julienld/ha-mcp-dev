"""Shared upstream integration step API over finite backend operations."""

import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, nullcontext
from typing import Annotated, Any, Literal

from pydantic import Field

from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.tool_api import BackendTools, ToolFailure
from ha_mcp.tools.coercion import JSON_STRING_COERCION

from .errors import raise_classified, raise_failure
from .flows.session import FlowSession
from .flows.settings import backend_flow_settings
from .integration_flow_steps import run_integration_step
from .integration_schema import describe_flow_form
from .integration_state import set_entry_enabled, set_log_level
from .integration_ws_commands import reject_ws_command_conflicts, send_ws_command
from .validation import validate_identifier_not_empty

logger = logging.getLogger(__name__)


def integration_changes_state(arguments: dict[str, Any]) -> bool:
    """Starting or reading a flow can execute its integration's own code."""
    return True


def _reject_set_integration_mode_conflicts(
    entry_id: str | None,
    domain: str | None,
    enabled: bool | None,
    config: dict[str, Any] | None,
    *,
    flow_args: list[str],
) -> None:
    """Reject ha_set_integration argument combinations that name two modes or none."""
    if domain is not None and entry_id is not None:
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "Pass either 'domain' (add a new integration) or "
                "'entry_id' (modify an existing one), not both",
                context={"entry_id": entry_id, "domain": domain},
            )
        )
    if enabled is not None and (domain is not None or config is not None or flow_args):
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "'enabled' is mutually exclusive with 'domain', 'config' and "
                "the flow parameters — enable/disable is a separate call",
                context={"entry_id": entry_id, "domain": domain},
            )
        )
    if domain is None and entry_id is None:
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "Nothing to do — provide 'domain' to add an "
                "integration, or 'entry_id' (its options flow, or with "
                "'enabled' to enable/disable it)",
                suggestions=[
                    "Use ha_get_integration() to find valid config entry IDs",
                ],
            )
        )


def _reject_log_persistence_without_level(
    log_persistence: str | None, log_level: str | None
) -> None:
    if log_persistence is not None and log_level is None:
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "log_persistence applies only together with log_level",
                suggestions=[
                    "Example: ha_set_integration(domain='zha', "
                    "log_level='DEBUG', log_persistence='permanent')"
                ],
            )
        )


def _reject_reconfigure_conflicts(
    reconfigure: bool, guards: dict[str, Any], domain: str | None, enabled: bool | None
) -> None:
    """Only reconfigure takes the identity guards, and it takes no domain or enabled."""
    if reconfigure and (domain is not None or enabled is not None):
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "Reconfigure mode requires entry_id; do not "
                "combine it with domain or enabled",
                context={"domain": domain, "enabled": enabled},
            )
        )
    rejected = sorted(name for name, value in guards.items() if value is not None)
    if rejected and not reconfigure:
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                "These parameters require reconfigure=True and were rejected: "
                + ", ".join(rejected),
                suggestions=[
                    "Pass reconfigure=True to use the identity safeguards of the "
                    "official reconfigure flow."
                ],
                # Not "ignored": the call was rejected and nothing ran.
                context={"rejected_parameters": rejected},
            )
        )


class IntegrationWriteTools(BackendTools):
    def _entry_write_guard(self, entry_id: str) -> AbstractAsyncContextManager[Any]:
        # Native owners serialize flow lifetimes and compare the snapshot again
        # after acquiring their entry lock. Remote backup stores add their scope.
        return nullcontext()

    @asynccontextmanager
    async def _integration_session(self) -> AsyncIterator[FlowSession]:
        session = FlowSession(
            self.backend,
            self.context,
            capture_backup=True,
            source_tool="ha_set_integration",
            entry_guard=self._entry_write_guard,
        )
        async with backend_flow_settings(self.backend, self.context):
            yield session

    @staticmethod
    def _set_integration_error_context(
        entry_id: str | None, domain: str | None
    ) -> dict[str, Any]:
        """Build the error-context dict for ha_set_integration failures."""
        error_context: dict[str, Any] = {}
        if entry_id is not None:
            error_context["entry_id"] = entry_id
        if domain is not None:
            error_context["domain"] = domain
        return error_context

    async def ha_set_integration(
        self,
        entry_id: Annotated[
            str | None,
            Field(
                description=("Config entry ID of an existing integration."),
                default=None,
            ),
        ] = None,
        enabled: Annotated[
            bool | None,
            Field(
                description=(
                    "True to enable, False to disable the entry. Mutually "
                    "exclusive with 'domain' and 'config'."
                ),
                default=None,
            ),
        ] = None,
        domain: Annotated[
            str | None,
            Field(
                description=(
                    "Integration domain to add (e.g. 'workday', 'local_calendar')."
                ),
                default=None,
            ),
        ] = None,
        config: Annotated[
            dict[str, Any] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "The values for the form the flow is at: one form per "
                    "call. Without flow_id it answers the new flow's first "
                    "form (after menu_choice, when the flow opens with a "
                    "menu). A key the form does not declare is refused before "
                    "anything is sent. On an existing entry (options, "
                    "reconfigure) a field you omit keeps its current value, "
                    "and a field set to null is cleared where the "
                    "integration's schema allows that field to be empty."
                ),
                default=None,
            ),
        ] = None,
        reconfigure: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "Use the existing config entry's official reconfigure flow "
                    "(its connection settings) instead of its options flow. "
                    "Every call except an abort checks the entry's identity "
                    "first. Without flow_id and config this opens the flow and "
                    "returns its first step; nothing is submitted. Continue "
                    "with the flow_id this entry's call returned: Home "
                    "Assistant does not say which entry a reconfigure flow "
                    "edits."
                ),
            ),
        ] = False,
        expected_device_id: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Requires reconfigure=True. Device registry ID the entry "
                    "must still own."
                ),
            ),
        ] = None,
        expected_unique_id: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Requires reconfigure=True, AND the ha_mcp_tools custom "
                    "component: Home Assistant does not expose a config "
                    "entry's unique_id over its API. Without the component "
                    "this is rejected — anchor on expected_device_id, "
                    "expected_mac or expected_entity_ids instead."
                ),
            ),
        ] = None,
        expected_mac: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Requires reconfigure=True. MAC or IEEE the entry's device "
                    "must still report."
                ),
            ),
        ] = None,
        expected_entity_ids: Annotated[
            list[str] | None,
            JSON_STRING_COERCION,
            Field(
                default=None,
                description=(
                    "Requires reconfigure=True. Exact entity IDs that must "
                    "remain associated with the entry."
                ),
            ),
        ] = None,
        log_level: Annotated[
            Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "DEFAULT"] | None,
            Field(
                default=None,
                description=(
                    "Set the integration's log level, like the integration "
                    "page's Enable/Disable debug logging: pass the integration "
                    "with 'domain' (no config flow runs) or 'entry_id', and "
                    "no other mode's parameters (log_persistence may accompany "
                    "it). Lasts through the next Home Assistant "
                    "restart unless log_persistence says otherwise. DEFAULT "
                    "clears the override: the integration then logs at the "
                    "inherited default level, and a level set for it in "
                    "configuration.yaml returns only after a restart."
                ),
            ),
        ] = None,
        log_persistence: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Only with log_level: how long Home Assistant keeps the "
                    "level. 'once' (default) through the next restart, "
                    "'permanent' after every restart until changed, 'none' "
                    "until the next restart. Home Assistant validates the value."
                ),
            ),
        ] = None,
        menu_choice: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "The option to pick at a menu step: with flow_id the "
                    "menu the flow is at, without it the menu a new flow "
                    "opens with. Refused when the step is not a menu or does "
                    "not offer the option."
                ),
            ),
        ] = None,
        subentry_type: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "With entry_id: the integration-defined subentry type "
                    "whose form to describe as subentry_schema; the flow is "
                    "aborted afterwards, unless a menu_choice finished it "
                    "(flow_type create_entry: saved)."
                ),
            ),
        ] = None,
        subentry_id: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "With entry_id and subentry_type: the existing subentry "
                    "whose reconfigure form to describe."
                ),
            ),
        ] = None,
        flow_id: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Continue an open flow: the flow_id a previous call "
                    "returned, with the same domain or entry_id (and "
                    "reconfigure=True for a reconfigure flow), until ha-mcp "
                    "restarts. With config or "
                    "menu_choice it answers the step; alone it returns the "
                    "step again."
                ),
            ),
        ] = None,
        abort: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "With flow_id: end the open flow without saving. A flow "
                    "Home Assistant no longer has, or one ha-mcp did not open "
                    "(or opened before it restarted), is an error."
                ),
            ),
        ] = False,
        ws_command: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "With entry_id: one of the integration's own '<domain>/' "
                    "WebSocket commands to send, as its panel in the HA UI "
                    "does (e.g. 'knx/get_knx_project'). Its result is "
                    "returned under result. Streaming commands are refused."
                ),
            ),
        ] = None,
        ws_data: Annotated[
            dict[str, Any] | None,
            JSON_STRING_COERCION,
            Field(
                default=None,
                description=(
                    "The ws_command's arguments, without 'type' and 'id'. "
                    "Home Assistant checks them against the command's "
                    "registered schema and returns its error when they do "
                    "not match."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Manage an integration (config entry): enable/disable, add, update options, reconfigure, or send its own commands.

        Modes (pick one):
        - Enable/disable: entry_id + enabled.
        - Add integration: domain (+ menu_choice, + config) — runs the
          domain's config flow one step per call, as the HA UI does.
        - Update options: entry_id (+ menu_choice, + config) — the entry's
          options flow (what the "Configure" button does in the HA UI), one
          step per call.
        - Reconfigure: entry_id + reconfigure=True — connection settings
          such as host, port, credentials, one step per call. Each call
          except an abort first checks the entry's identity; the first call
          without config returns the flow's first step.
        - Log level: log_level + domain (or entry_id) — sets how much the
          integration logs; read it back with ha_get_integration's log_level.
        - Integration command: entry_id + ws_command (+ ws_data) — what the
          integration's panel sends (KNX project, entities, telegrams).
          Home Assistant marks none of these commands as read-only, so a read
          such as knx/get_knx_project goes through this tool too.

        Flows, one step per call: a call answers the step the flow is at and
        returns Home Assistant's next answer. A form comes back with its
        fields (type, default, current value, Home Assistant's help text) and
        flow_id; a menu with menu_options. Answer with flow_id and config (a
        form) or menu_choice (a menu); flow_id alone returns the step again,
        and flow_id with abort=True ends the flow. Without flow_id a new flow
        starts: its first form gets config, and without config the call
        returns that first step. A form Home Assistant rejects is an error
        with errors and error_text (Core's text), and the flow stays open to
        correct it. A flow stays open until Home Assistant finishes
        it or you abort it; while a setup flow is open, Home Assistant
        refuses another one for the same device as already_in_progress.

        WHEN NOT TO USE:
        - Helpers (template, group, utility_meter, ...): use
          ha_config_set_helper. `otp` is the user's to set up in the HA UI: its
          secret is a credential enrolled in an authenticator app; do not create it.
        - Config subentries: use
          ha_config_set_helper(helper_type='config_subentry'); subentry_type
          here describes their form; a menu_choice that finishes the flow
          saves the subentry.
        - Removing an entry: use ha_remove_helpers_integrations.
        - ha-mcp's own ha_mcp_tools entries are refused: manage them in the HA
          UI, or (server settings, developer mode on) ha_dev_manage_settings /
          ha_dev_manage_server.

        Use ha_get_integration() to find entry IDs, and
        ha_get_integration(entry_id=..., include_schema=True) to inspect the
        options fields. Its supports_reconfigure field tells you whether an
        entry qualifies for reconfigure=True, and
        ha_get_integration(entry_id=..., include_ws_commands=True) lists the
        commands ws_command accepts with their schemas.

        Caveats: adding an integration runs its config flow exactly as the HA
        UI would (may pair devices, scan the network, create entities). Flows
        requiring a browser step (OAuth) are refused at that step and
        aborted. A progress step (Home Assistant working in the background)
        is waited out for up to 120 s; after that the error carries flow_id
        to ask again. When Home Assistant does not answer a submit or a
        progress poll (or, on reconfigure, answers with any 5xx), the error
        carries status applied_but_unverified: the entry may exist or the
        change may be saved, so check it before retrying. An aborted flow
        returns Core's own text next to the key (reason_text). Reconfigure
        edits the settings a live integration connects with: a wrong host or
        credential takes it offline, and there is no automatic rollback. A
        finished reconfigure waits for the reload Home Assistant runs and
        reports the entry's state as entry_state: status applied_and_verified
        once it is loaded, applied_but_unverified otherwise.

        EXAMPLES:
        - Add: ha_set_integration(domain="local_calendar", config={"calendar_name": "Chores"})
        - Add in two steps: ha_set_integration(domain="knx", config={"connection_type": "routing"}) returns the routing form and flow_id, then ha_set_integration(domain="knx", flow_id="...", config={})
        - Answer a menu: ha_set_integration(domain="...", flow_id="...", menu_choice="<one of menu_options>")
        - See the setup form first: ha_set_integration(domain="workday")
        - Update options: ha_set_integration(entry_id="abc123", config={"scan_interval": 30})
        - Reconfigure: ha_set_integration(entry_id="abc123", reconfigure=True), then ha_set_integration(entry_id="abc123", reconfigure=True, flow_id="...", config={"host": "10.0.0.5"})
        - Cancel a flow: ha_set_integration(domain="knx", flow_id="...", abort=True)
        - Debug logging: ha_set_integration(domain="zha", log_level="DEBUG"), then log_level="DEFAULT" to stop
        - KNX project: ha_set_integration(entry_id="abc123", ws_command="knx/get_knx_project")
        """
        async with self._integration_session() as session:
            # Only reconfigure takes these; every other mode refuses them.
            reconfigure_guards: dict[str, Any] = {
                "expected_device_id": expected_device_id,
                "expected_unique_id": expected_unique_id,
                "expected_mac": expected_mac,
                "expected_entity_ids": expected_entity_ids,
            }
            try:
                _reject_log_persistence_without_level(log_persistence, log_level)
                _reject_reconfigure_conflicts(
                    reconfigure, reconfigure_guards, domain, enabled
                )
                if (
                    entry_id is not None
                    and not abort
                    and log_level is None
                    and ws_command is None
                ):
                    entry_id = validate_identifier_not_empty(entry_id, "entry_id")
                    await session._backup(entry_id)
                flow_args = {
                    "flow_id": flow_id,
                    "menu_choice": menu_choice,
                    "abort": abort or None,
                }
                if ws_command is not None or ws_data is not None:
                    reject_ws_command_conflicts(
                        entry_id,
                        ws_command,
                        domain=domain,
                        enabled=enabled,
                        config=config,
                        log_level=log_level,
                        subentry_type=subentry_type,
                        subentry_id=subentry_id,
                        reconfigure=reconfigure or None,
                        **flow_args,
                    )
                    return await send_ws_command(
                        session,
                        validate_identifier_not_empty(entry_id, "entry_id"),
                        validate_identifier_not_empty(ws_command, "ws_command"),
                        ws_data,
                    )
                if subentry_type is not None or subentry_id is not None:
                    modes = {
                        "enabled": enabled is not None,
                        "config": config is not None,
                        "reconfigure": reconfigure,
                        "log_level": log_level is not None,
                        "flow_id": flow_id is not None,
                        "abort": abort,
                    }
                    return await describe_flow_form(
                        session,
                        domain=domain,
                        entry_id=entry_id,
                        subentry_type=subentry_type,
                        subentry_id=subentry_id,
                        menu_choice=menu_choice,
                        other_modes=[name for name, given in modes.items() if given],
                    )
                if log_level is not None:
                    return await set_log_level(
                        session,
                        entry_id,
                        domain,
                        log_level,
                        other_modes=config is not None
                        or enabled is not None
                        or reconfigure
                        or any(v is not None for v in flow_args.values()),
                        persistence=log_persistence,
                    )

                if reconfigure:
                    return await run_integration_step(
                        session,
                        domain=None,
                        entry_id=entry_id,
                        flow_id=flow_id,
                        config=config,
                        menu_choice=menu_choice,
                        abort=abort,
                        expected_identity={
                            "device_id": expected_device_id,
                            "unique_id": expected_unique_id,
                            "mac": expected_mac,
                            "entity_ids": list(expected_entity_ids or []),
                        },
                    )

                _reject_set_integration_mode_conflicts(
                    entry_id,
                    domain,
                    enabled,
                    config,
                    flow_args=[name for name, value in flow_args.items() if value],
                )

                if domain is not None:
                    validate_identifier_not_empty(
                        domain,
                        "domain",
                        suggestions=[
                            "Pass the integration domain, e.g. 'workday' or "
                            "'local_calendar'",
                        ],
                    )
                    return await run_integration_step(
                        session,
                        domain=domain.strip().lower(),
                        entry_id=None,
                        flow_id=flow_id,
                        config=config,
                        menu_choice=menu_choice,
                        abort=abort,
                    )

                # Empty/whitespace entry_id would surface as a misleading HA
                # "config entry not found" from the backend call.
                entry_id = validate_identifier_not_empty(
                    entry_id,
                    "entry_id",
                    suggestions=[
                        "Use ha_get_integration() to find valid config entry IDs",
                    ],
                )

                if enabled is not None:
                    return await set_entry_enabled(session, entry_id, enabled)

                # Options mode: one step of the entry's options flow.
                return await run_integration_step(
                    session,
                    domain=None,
                    entry_id=entry_id,
                    flow_id=flow_id,
                    config=config,
                    menu_choice=menu_choice,
                    abort=abort,
                )

            except ToolFailure:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to set integration: {e}")
                error_context = self._set_integration_error_context(entry_id, domain)
                raise_classified(
                    e,
                    context=error_context,
                    suggestions=[
                        "Verify the integration domain is spelled correctly and "
                        "is installed (custom integrations must be installed "
                        "before a config flow can start)",
                    ]
                    if domain is not None
                    else [
                        "Use ha_get_integration() to find valid config entry IDs",
                    ],
                )
                return None  # unreachable: exception_to_structured_error raises
