"""Transport-neutral recovery advice for a missing Core registry identity."""

from typing import Any

from .snapshot_payloads import BackupRestoreError


def deleted_entity_error(entity_id: str, found: dict[str, Any]) -> BackupRestoreError:
    """The refusal for a gone entry, from what ``_lookup`` knows of it."""
    again = "If this backup is from an earlier edit, restore it once the entity is back"
    if "deleted" not in found:
        suggestions = [
            "Restart Home Assistant: if what provides the entity is still "
            "there, it adds the entity again with the registry settings it "
            "had while its config entry exists, and for 30 days after that "
            "entry, or an entity without one, was removed. A reload does not "
            "bring back a stored helper's entity",
            again,
        ]
    elif (deleted := found["deleted"]) is None:
        suggestions = [
            "Home Assistant no longer keeps this entity's registry settings: "
            "an entity added again gets a new registry entry, which this "
            "backup cannot be restored over. Set the entity with ha_set_entity "
            "instead"
        ]
    else:
        kept = (
            f"until {deleted['kept_until']}"
            if deleted.get("kept_until")
            else "while its config entry exists"
        )
        suggestions = [
            f"Home Assistant keeps the registry settings of {deleted['entity_id']} "
            f"{kept} and gives them back when the entity is added again. If "
            "what provides the entity is still there, restart Home Assistant; "
            "a reload does not bring back a stored helper's entity",
            again,
        ]
    error = BackupRestoreError(
        f"{entity_id} is no longer in the entity registry",
        reason="entry_deleted",
        suggestions=suggestions,
    )
    return error
