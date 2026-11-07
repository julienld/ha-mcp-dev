"""Restore integration options and enabled state through existing Core owners."""

import json
from dataclasses import dataclass, field
from functools import partial
from typing import Any, cast

from homeassistant.helpers.json import json_bytes

from ha_mcp.errors import HomeAssistantError
from ha_mcp.runtime.flows.entry import update_config_entry_options
from ha_mcp.runtime.flows.session import FlowSession
from ha_mcp.runtime.flows.settings import FlowSettings, bind_flow_settings
from ha_mcp.runtime.integration_snapshot import restore_integration
from ha_mcp.runtime.snapshot_flow_values import _apply_and_verify, _verify_readback
from ha_mcp.runtime.snapshot_payloads import (
    BackupRestoreError,
    InvalidBackupSnapshotError,
)
from ha_mcp.tool_api import CallContext, ToolFailure
from ha_mcp.utils.config_hash import json_values_equal
from ha_mcp.utils.owned_executor import await_owned_io

from .integration_state import NativeIntegrationState
from .registry_access import authorize_actor
from .snapshot_sources import integration_snapshot


@dataclass(slots=True)
class NativeIntegrationRestore:
    manager: Any
    actor: CallContext
    data: dict[str, Any]
    entry: Any = field(default=None, init=False, repr=False)

    async def current(self) -> dict[str, Any] | None:
        config, identifier = self.data["config"], self.data["entity_id"]
        if (
            not isinstance(config, dict)
            or config.get("entry_id") != identifier
            or "data" in config
        ):
            raise InvalidBackupSnapshotError(
                "Integration snapshot does not match its public identity"
            )
        await authorize_actor(self.actor, self.manager.backend.authorize)
        self.entry = self.manager.hass.config_entries.async_get_entry(identifier)
        return await self.read() if self.entry is not None else None

    comparison = current

    async def read(self) -> dict[str, Any] | None:
        await authorize_actor(self.actor, self.manager.backend.authorize)
        result = await integration_snapshot(self.manager.hass, self.data["entity_id"])
        await authorize_actor(self.actor, self.manager.backend.authorize)
        return cast(dict[str, Any], result)

    async def apply(self, before: Any) -> dict[str, Any]:
        if before is None or self.entry is None:
            raise BackupRestoreError(
                "The integration no longer exists; add it again through its Core flow.",
                reason="entry_deleted",
                apply_status="not_applied",
            )
        return await await_owned_io(self._apply(before))

    async def _apply(self, before: dict[str, Any]) -> dict[str, Any]:
        await authorize_actor(self.actor, self.manager.backend.authorize)
        current = await self.read()
        if self.manager.hass.config_entries.async_get_entry(
            self.data["entity_id"]
        ) is not self.entry or not json_values_equal(current, before):
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "Integration changed during the safety capture",
                status="not_started",
            )
        result = await restore_integration(
            self, self.data["entity_id"], self.data["config"]
        )
        try:
            await authorize_actor(self.actor, self.manager.backend.authorize)
        except ToolFailure as error:
            raise ToolFailure(
                error.code,
                "Integration restore was dispatched but its result is no longer authorized",
                status="outcome_unknown",
            ) from None
        live = self.manager.hass.config_entries.async_get_entry(self.data["entity_id"])
        if live is not self.entry or (live.disabled_by is None) != (
            self.data["config"].get("disabled_by") is None
        ):
            raise ToolFailure(
                "OUTCOME_UNKNOWN",
                "Core did not retain the requested integration state; inspect it before retrying",
                status="outcome_unknown",
            )
        return cast(dict[str, Any], result)

    async def set_disabled(self, disabled_by: str | None) -> Any:
        await authorize_actor(self.actor, self.manager.backend.authorize)
        identifier = self.data["entity_id"]
        if (
            self.manager.hass.config_entries.async_get_entry(identifier)
            is not self.entry
        ):
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "Integration owner changed before the restore",
                status="not_started",
            )
        owner = NativeIntegrationState(
            self.manager.hass, self.manager.backend.authorize
        )
        result = await owner._enabled(
            {
                "entry_id": identifier,
                "enabled": disabled_by is None,
                "expected_entry": json.loads(json_bytes(self.entry.as_json_fragment)),
                "expected_owner": self.entry,
            },
            self.actor,
        )
        try:
            await authorize_actor(self.actor, self.manager.backend.authorize)
        except ToolFailure as error:
            raise ToolFailure(
                error.code,
                "Integration state was dispatched but is no longer authorized",
                status="outcome_unknown",
            ) from None
        return result

    async def restore_options(
        self, config: dict[str, Any], current_options: dict[str, Any]
    ) -> None:
        identifier = self.data["entity_id"]
        metadata = json.loads(json_bytes(self.entry.as_json_fragment))
        session = FlowSession(
            self.manager.backend,
            self.actor,
            expected_modified_at=metadata.get("modified_at"),
        )

        async def read_options() -> dict[str, Any] | None:
            result = await self.read()
            if result is not None and "options" not in result:
                raise HomeAssistantError("Integration options could not be read safely")
            return result

        with bind_flow_settings(
            FlowSettings(lambda: self.manager.policy.flag("redact_secrets"))
        ):
            await _apply_and_verify(
                f"{config.get('domain')} integration",
                partial(
                    update_config_entry_options,
                    session,
                    identifier,
                    config["options"],
                    expected_domain=config.get("domain"),
                    keep_current_values=False,
                    fixed_options=current_options,
                ),
                partial(
                    _verify_readback,
                    read_options,
                    {"options": config["options"]},
                    ("options",),
                ),
            )
