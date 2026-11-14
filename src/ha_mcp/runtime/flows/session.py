"""Finite flow ports used by the existing walkers, without a network client."""

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from typing import Any, cast

from ha_mcp.errors import HomeAssistantAuthError
from ha_mcp.tool_api import Backend, BackendTools, CallContext, ToolFailure


class FlowSession(BackendTools):
    """Config/options/subentry operations only; no URL, token, HTTP or WS API."""

    def __init__(
        self,
        backend: Backend,
        context: CallContext,
        *,
        helper_type: str | None = None,
        capture_backup: bool = False,
        expected_modified_at: float | None = None,
        source_tool: str = "ha_config_set_helper",
        entry_guard: Callable[[str], AbstractAsyncContextManager[Any]] | None = None,
    ) -> None:
        super().__init__(backend, context)
        self.helper_type = helper_type
        self.capture_backup = capture_backup
        self.expected_modified_at = expected_modified_at
        self.source_tool = source_tool
        self.entry_guard = entry_guard
        self.warnings: list[str] = []
        self._captured_entries: dict[str, dict[str, Any]] = {}

    @property
    def cache_owner(self) -> Any:
        """Stable owner for schema caches across invocation-local sessions."""
        return getattr(self.backend, "cache_owner", self.backend)

    def write_scope(self, entry_id: str) -> AbstractAsyncContextManager[Any]:
        """An outer backup-store guard; Core flow ownership stays with the backend."""
        return self.entry_guard(entry_id) if self.entry_guard else nullcontext()

    async def start_config_flow(self, handler: str) -> dict[str, Any]:
        return await self._mapping(
            "config.flow.start", {"kind": "config", "handler": handler}, self.context
        )

    async def start_reconfigure_flow(
        self, domain: str, entry_id: str, *, expected_modified_at: float | None = None
    ) -> dict[str, Any]:
        expected = await self._backup(entry_id)
        return await self._mapping(
            "config.flow.start",
            {
                "kind": "config",
                "handler": domain,
                "entry_id": entry_id,
                **(
                    {"expected_modified_at": expected_modified_at}
                    if expected_modified_at is not None
                    else expected
                ),
            },
            self.context,
        )

    async def start_options_flow(self, entry_id: str) -> dict[str, Any]:
        expected = await self._backup(entry_id)
        return await self._mapping(
            "config.flow.start",
            {"kind": "options", "handler": entry_id, **expected},
            self.context,
        )

    async def start_config_subentry_flow(
        self,
        entry_id: str,
        subentry_type: str,
        *,
        subentry_id: str | None = None,
        show_advanced_options: bool | None = None,
    ) -> dict[str, Any]:
        expected = (
            await self._backup(entry_id, subentry_id, subentry_type)
            if subentry_id
            else self._expected_revision()
        )
        return await self._mapping(
            "config.flow.start",
            {
                "kind": "subentry",
                "handler": [entry_id, subentry_type],
                "subentry_id": subentry_id,
                "show_advanced_options": show_advanced_options,
                **expected,
            },
            self.context,
        )

    async def submit_config_flow_step(
        self, flow_id: str, user_input: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._mapping(
            "config.flow.configure",
            {"flow_id": flow_id, "user_input": user_input},
            self.context,
        )

    submit_options_flow_step = submit_config_flow_step
    submit_config_subentry_flow_step = submit_config_flow_step

    async def read_flow(self, kind: str, flow_id: str) -> dict[str, Any]:
        """Re-enter only this caller's owned Core flow, without user input."""
        return await self._mapping(
            "config.flow.read", {"kind": kind, "flow_id": flow_id}, self.context
        )

    async def read_flow_translations(
        self, domain: str | Sequence[str], category: str, *, language: str = "en"
    ) -> dict[str, Any]:
        return await self._mapping(
            "helpers.translations",
            {"handler": domain, "category": category, "language": language},
            self.context,
        )

    async def integration_commands(self, domain: str) -> dict[str, Any]:
        return await self._mapping(
            "integrations.commands", {"domain": domain}, self.context
        )

    async def send_integration_command(
        self, entry_id: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._mapping(
            "integrations.command.execute",
            {"entry_id": entry_id, "message": message},
            self.context,
        )

    async def abort_config_flow(self, flow_id: str) -> dict[str, Any]:
        return await self._mapping(
            "config.flow.abort", {"flow_id": flow_id}, self.context
        )

    abort_options_flow = abort_config_flow
    abort_config_subentry_flow = abort_config_flow

    async def get_config_entry(self, entry_id: str) -> dict[str, Any]:
        return await self._mapping(
            "config.entries.read", {"entry_id": entry_id}, self.context
        )

    async def list_config_entries(self, **query: Any) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self.backend.execute("config.entries.list", query, self.context),
        )

    async def list_config_subentries(self, entry_id: str) -> dict[str, Any]:
        rows = await self.backend.execute(
            "config.subentries.list", {"entry_id": entry_id}, self.context
        )
        return {"success": True, "result": rows}

    async def _backup(
        self,
        entry_id: str,
        subentry_id: str | None = None,
        subentry_type: str | None = None,
    ) -> dict[str, Any]:
        if not self.capture_backup:
            return self._expected_revision()
        key = f"{entry_id}/{subentry_id}" if subentry_id else entry_id
        if key in self._captured_entries:
            return self._captured_entries[key]
        try:
            current = await self.get_config_entry(entry_id)
        except HomeAssistantAuthError, PermissionError, ToolFailure:
            raise
        except Exception as error:  # noqa: BLE001 - best-effort capture, before mutation
            return self._capture_unavailable(key, error, "reading the config entry")
        helper_type = self.helper_type
        if helper_type is None:
            from ha_mcp.runtime.helper_flows import helper_flow_types

            try:
                kinds = await helper_flow_types(self)
            except HomeAssistantAuthError, PermissionError, ToolFailure:
                raise
            except Exception as error:  # noqa: BLE001 - capture classification is best effort
                return self._capture_unavailable(
                    key, error, "identifying the helper flow", current
                )
            helper_type = (
                current.get("domain")
                if current.get("domain") in kinds
                else "integration"
            )
        kind = (
            "subentry"
            if subentry_id
            else "integration"
            if helper_type == "integration"
            else "flow"
        )
        result = await self._mapping(
            "helpers.backup.capture",
            {
                "kind": kind,
                "helper_type": helper_type,
                "source_tool": self.source_tool,
                **(
                    {"backup_domain": "integration", "current_entry": current}
                    if kind == "integration"
                    else {}
                ),
                "action": "update",
                "backup_id": f"{entry_id}/{subentry_id}" if subentry_id else entry_id,
                "entry_id": entry_id,
                **(
                    {"subentry_id": subentry_id, "subentry_type": subentry_type}
                    if subentry_id
                    else {}
                ),
            },
            self.context,
        )
        self.warnings.extend(result.get("warnings", []))
        expected = (
            self._expected_revision()
            if self.expected_modified_at is not None
            else (
                {"expected_modified_at": current["modified_at"]}
                if "modified_at" in current
                else {}
            )
        )
        self._captured_entries[key] = expected
        return expected

    def _capture_unavailable(
        self,
        key: str,
        error: Exception,
        reason: str,
        current: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.warnings.append(
            f"No pre-write backup was taken: {type(error).__name__} while {reason}"
        )
        expected = self._expected_revision()
        if not expected and current is not None and "modified_at" in current:
            expected = {"expected_modified_at": current["modified_at"]}
        self._captured_entries[key] = expected
        return expected

    def _expected_revision(self) -> dict[str, Any]:
        return (
            {"expected_modified_at": self.expected_modified_at}
            if self.expected_modified_at is not None
            else {}
        )

    async def _mapping(
        self, operation: str, arguments: dict[str, Any], context: CallContext
    ) -> dict[str, Any]:
        try:
            return cast(
                dict[str, Any],
                await self.backend.execute(operation, arguments, context),
            )
        except PermissionError as error:
            raise ToolFailure(
                "AUTH_REQUIRED", "Flow admission was revoked.", status="not_started"
            ) from error
