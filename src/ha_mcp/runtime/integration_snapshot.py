"""Upstream integration restore sequencing over finite owner ports."""

from __future__ import annotations

import copy
from typing import Any, Literal, Protocol

from ha_mcp.runtime.redaction import placeholder_option_keys
from ha_mcp.runtime.snapshot_payloads import BackupRestoreError
from ha_mcp.utils.config_hash import json_values_equal


class IntegrationRestorePorts(Protocol):
    async def read(self) -> dict[str, Any] | None: ...
    async def set_disabled(self, disabled_by: str | None) -> Any: ...
    async def restore_options(
        self, config: dict[str, Any], current_options: dict[str, Any]
    ) -> None: ...


def integration_snapshot_value(
    row: dict[str, Any], *, secret_scrub_degraded: bool = False
) -> dict[str, Any]:
    """Keep restorable options only after the real component scrub succeeded."""
    result = copy.deepcopy(
        {key: value for key, value in row.items() if key not in {"data", "subentries"}}
    )
    options = result.pop("options", None)
    if not isinstance(options, dict):
        result["options_unavailable"] = "options_missing"
    elif secret_scrub_degraded:
        result["options_unavailable"] = "secret_scrub_degraded"
    elif placeholder_option_keys(options):
        result["options_unavailable"] = "redacted_options"
    else:
        result["options"] = options
    return result


async def restore_integration(
    ports: IntegrationRestorePorts, entity_id: str, config: Any
) -> Any:
    current = await ports.read()
    if current is None:
        raise BackupRestoreError(
            f"Config entry {entity_id} ({config.get('domain')}) no longer exists. "
            "An integration snapshot holds only the entry's metadata, options and "
            "enabled state, so it cannot recreate a deleted entry. Nothing was "
            "changed; add the integration again to recover it.",
            reason="entry_deleted",
            suggestions=[
                "Add it again with ha_set_integration, or have the user add it in "
                "the HA UI when it needs their credentials."
            ],
        )
    options = config.get("options")
    if "options" in config and not isinstance(options, dict):
        raise BackupRestoreError(
            "The integration snapshot's options are not an object. Nothing was "
            "changed.",
            reason="invalid_snapshot",
        )
    if options is not None and "options" not in current:
        raise BackupRestoreError(
            f"The current options of config entry {entity_id} cannot be read "
            f"({current.get('options_unavailable')}), so the snapshot's options "
            "cannot be checked against them. Nothing was changed.",
            reason="options_unreadable",
        )
    not_restored = _options_not_restored(config, current)
    disabled_by = None if config.get("disabled_by") is None else "user"
    enable_first = disabled_by is None and current.get("disabled_by") is not None
    if enable_first:
        result = await ports.set_disabled(None)
    if (
        not_restored is None
        and options is not None
        and not json_values_equal(options, current["options"])
    ):
        try:
            await ports.restore_options(config, current["options"])
        except BackupRestoreError as err:
            if not enable_first:
                raise
            raise _enabled_then_failed(entity_id, err) from err
    if not enable_first:
        result = await ports.set_disabled(disabled_by)
    if not_restored is not None:
        verification_status, why = not_restored
        raise BackupRestoreError(
            f"The enabled state of config entry {entity_id} was restored, but "
            f"its options were not: {why}.",
            apply_status="applied",
            verification_status=verification_status,
            reason="options_not_restored",
        )
    return result


def _enabled_then_failed(entity_id: str, err: BackupRestoreError) -> BackupRestoreError:
    """``err`` from the options restore of an entry the restore enabled first."""
    if err.outcome["apply_status"] != "not_applied":
        detail = f"then its options restore failed: {err}"
    elif err.outcome.get("reason"):
        detail = f"but its options were not restored: {err}"
    else:
        detail = "but its options were not restored: the options flow refused them"
    failed: BackupRestoreError = BackupRestoreError(
        f"Config entry {entity_id} was enabled, {detail}",
        # The enable applied; the options restore keeps its own status.
        **{
            **err.outcome,
            "apply_status": "applied",
            "options_apply_status": err.outcome["apply_status"],
        },
    )
    return failed


def _options_not_restored(
    config: Any, current: dict[str, Any]
) -> tuple[Literal["unavailable", "mismatched"], str] | None:
    """``(verification_status, why)`` for options a restore cannot put back."""
    if "options_unavailable" in config or "options" not in config:
        why = config.get("options_unavailable", "taken before options were captured")
        return ("unavailable", f"the snapshot holds none ({why})")
    if config.get("options") == {} and current["options"]:
        return (
            "mismatched",
            "the snapshot's are empty, which an options flow cannot produce",
        )
    return None
