"""Auto-backup handlers for integration config entries.

A snapshot holds the entry's Core row, its enabled state and, read through the
ha_mcp_tools component, its options. Options are kept only when the component
could scrub them and they hold no redaction placeholder; otherwise
``options_unavailable`` says why. ``entry.data`` (credentials) is never read,
and neither are subentries: ha_set_integration does not edit them, and Core
has no API to put a subentry's data back under a deleted entry.

A restore refuses a deleted entry rather than sending Core a command for an
entry it no longer has. Otherwise it enables the entry first when the snapshot
was enabled, so the options flow runs on a loaded entry, puts back options that
differ through the options flow and reads them back, then applies the enabled
state. Options it cannot put back (the snapshot has none, or empty ones an
options flow cannot produce) fail the restore after the enabled state is set.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from .backup_entity_ids import _manager
from .runtime.integration_snapshot import (
    _enabled_then_failed as _enabled_then_failed,
)
from .runtime.integration_snapshot import (
    _options_not_restored as _options_not_restored,
)
from .runtime.integration_snapshot import (
    integration_snapshot_value,
)
from .runtime.integration_snapshot import (
    restore_integration as shared_restore_integration,
)

if TYPE_CHECKING:
    pass


async def fetch_integration(client: Any, entity_id: str) -> dict[str, Any] | None:
    from .tools import component_config_entries
    from .tools.component_api import component_supports, get_component_caps

    bm = _manager()
    read = await component_config_entries.fetch_config_entries(
        client, entry_id=entity_id
    )
    if read is None:
        # An installed component whose command failed is not a missing one.
        caps = await get_component_caps(client)
        why = (
            "component_read_failed"
            if component_supports(caps, "config_entries")
            else "component_unavailable"
        )
        items = bm._require_list(
            await bm._ws_send(client, {"type": "config_entries/get"}),
            "config_entries/get",
        )
        for item in items:
            if item.get("entry_id") == entity_id:
                return {**item, "options_unavailable": why}
        return None
    if not read.rows:
        return None
    return integration_snapshot_value(
        read.rows[0], secret_scrub_degraded=read.secret_scrub_degraded
    )


async def _read_options(client: Any, entry_id: str) -> Any:
    # Options the component can no longer read safely leave the restore
    # unverified rather than failing it as a mismatch.
    from .client.rest_client import HomeAssistantError

    row = await fetch_integration(client, entry_id)
    if row is not None and "options" not in row:
        raise HomeAssistantError(f"options unreadable: {row['options_unavailable']}")
    return row


async def _set_disabled_by(client: Any, entry_id: str, disabled_by: Any) -> Any:
    return await _manager()._ws_send(
        client,
        {
            "type": "config_entries/disable",
            "entry_id": entry_id,
            "disabled_by": disabled_by,
        },
    )


async def restore_integration(client: Any, entity_id: str, config: Any) -> Any:
    return await shared_restore_integration(
        _LegacyIntegrationRestore(client, entity_id), entity_id, config
    )


async def _restore_options(
    client: Any, entity_id: str, config: Any, current_options: dict[str, Any]
) -> None:
    from .tools.config_entry_flow import restore_config_entry_options

    options = config["options"]
    from .runtime.snapshot_flow_values import _apply_and_verify, _verify_readback

    await _apply_and_verify(
        f"{config.get('domain')} integration",
        partial(
            restore_config_entry_options,
            client,
            entity_id,
            options,
            expected_domain=config.get("domain"),
            fixed_options=current_options,
        ),
        partial(
            _verify_readback,
            partial(_read_options, client, entity_id),
            {"options": options},
            ("options",),
        ),
    )


class _LegacyIntegrationRestore:
    def __init__(self, client: Any, entry_id: str) -> None:
        self.client, self.entry_id = client, entry_id

    async def read(self) -> dict[str, Any] | None:
        return await fetch_integration(self.client, self.entry_id)

    async def set_disabled(self, disabled_by: str | None) -> Any:
        return await _set_disabled_by(self.client, self.entry_id, disabled_by)

    async def restore_options(
        self, config: dict[str, Any], current_options: dict[str, Any]
    ) -> None:
        await _restore_options(self.client, self.entry_id, config, current_options)


__all__ = [
    "_enabled_then_failed",
    "_options_not_restored",
    "fetch_integration",
    "restore_integration",
]
