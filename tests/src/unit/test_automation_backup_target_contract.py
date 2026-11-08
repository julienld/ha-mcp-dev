"""Automation snapshots follow Main's current entity_id/config.id contract."""

from ha_mcp.tools.auto_backup import automation_backup_target


def test_create_without_a_current_target_cannot_snapshot_a_retired_identifier():
    assert (
        automation_backup_target(
            {
                "entity_id": None,
                "identifier": "automation.unrelated",
                "config": {"alias": "New automation"},
            }
        )
        == ""
    )
