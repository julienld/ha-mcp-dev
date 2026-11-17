"""Named reload services and public result values, independent of transport."""

from typing import Any

from ha_mcp.errors import ErrorCode, create_error_response

from .errors import raise_failure

NAMED_RELOADS = {
    "all": ("homeassistant", "reload_all"),
    "core": ("homeassistant", "reload_core_config"),
    "themes": ("frontend", "reload_themes"),
    "custom_templates": ("homeassistant", "reload_custom_templates"),
}
RELOAD_WAIT_SECONDS = 120.0
RELOAD_ALL_FAILED_HINT = (
    "A failed configuration check stops reload-all before anything reloads. "
    "Any other failure is one integration's: the other reloads were started "
    "too and may have finished, still be running or have failed, so check "
    "Home Assistant's log before reloading again"
)


def reload_service(target: str, reloadable: list[str]) -> tuple[str, str]:
    """Resolve aliases or an actual Core domain service, without a domain list."""
    if target in NAMED_RELOADS:
        return NAMED_RELOADS[target]
    if target in reloadable:
        return target, "reload"
    valid_targets = [*NAMED_RELOADS, *sorted(reloadable)]
    domain = target.removesuffix("s")
    raise_failure(
        create_error_response(
            ErrorCode.VALIDATION_INVALID_PARAMETER,
            f"Invalid reload target: Home Assistant has no '{target}.reload' service"
            + (f". Did you mean '{domain}'?" if domain in reloadable else ""),
            context={"target": target, "valid_targets": valid_targets},
            suggestions=[
                f"Use one of: {', '.join(valid_targets)}",
                "An integration that is not loaded has no reload service: "
                "restart Home Assistant (ha_restart) to load its first YAML block",
            ],
        )
    )


def reload_target_result(target: str, domain: str, service: str) -> dict[str, Any]:
    return {
        "success": True,
        "message": f"Home Assistant ran {domain}.{service}",
        "target": target,
        "service": f"{domain}.{service}",
    }

def reload_entry_result(entry_id: str, require_restart: bool) -> dict[str, Any]:
    if require_restart:
        return {
            "success": True,
            "message": f"Config entry {entry_id} cannot be hot-reloaded; a Home Assistant restart is required for changes to take effect",
            "reloaded": False,
            "require_restart": True,
            "entry_id": entry_id,
        }
    return {
        "success": True,
        "message": f"Reloaded config entry {entry_id}",
        "reloaded": True,
        "require_restart": False,
        "entry_id": entry_id,
    }


def restart_scheduled_result() -> dict[str, Any]:
    return {
        "success": True,
        "requested": True,
        "scheduled": True,
        "message": "Home Assistant restart scheduled. This MCP server stops with Home Assistant; completion cannot be confirmed by this invocation.",
        "warnings": [
            "The request is revalidated before Core receives it. Calls may fail while Home Assistant stops and starts; reconnect after it becomes available."
        ],
    }


def restart_precheck_warnings(
    recorder: dict[str, Any] | None, backup: dict[str, Any] | None, *, safe_mode: bool
) -> list[str]:
    """Refuse what Core would refuse; return the warnings for the reply."""
    warnings = [
        "Calls may fail while this server starts. Try again after a few seconds."
    ]
    if safe_mode:
        warnings.append(
            "Safe mode loads no custom integrations, and this server is "
            "one: it stays down until Home Assistant is next "
            "restarted normally."
        )
    # A missing field (older Core, renamed key) means the check was not made,
    # so it warns like an unanswered command instead of passing silently.
    if recorder is None or not isinstance(recorder.get("migration_in_progress"), bool):
        warnings.append(
            "Could not read the recorder status to check for a database "
            "upgrade; Home Assistant refuses to restart during one."
        )
    elif recorder.get("migration_in_progress"):
        raise_failure(
            create_error_response(
                ErrorCode.RESOURCE_LOCKED,
                "A database upgrade is in progress - restart refused",
                details=(
                    "Home Assistant cannot restart while the recorder "
                    "is upgrading its database."
                ),
                context={"recorder": recorder, "execution_status": "not_started"},
                suggestions=[
                    "Wait for the upgrade to finish, then call "
                    "ha_restart(confirm=True) again"
                ],
            )
        )
    state = backup.get("state") if backup else None
    if not isinstance(state, str):
        warnings.append(
            "Could not read the backup status to check for a running "
            "backup; Home Assistant cannot restart during one."
        )
    elif state != "idle":
        raise_failure(
            create_error_response(
                ErrorCode.RESOURCE_LOCKED,
                f"Backup manager is busy ({state}) - restart refused",
                details=(
                    "Home Assistant cannot restart while the backup manager is "
                    "busy creating, receiving or restoring one."
                ),
                context={"backup_state": state, "execution_status": "not_started"},
                suggestions=[
                    "Wait for the backup to finish, then call "
                    "ha_restart(confirm=True) again"
                ],
            )
        )
    return warnings
