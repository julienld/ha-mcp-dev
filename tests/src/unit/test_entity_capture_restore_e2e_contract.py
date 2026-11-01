"""The entity restore scenarios must select the history that the writer creates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ..e2e.workflows.auto_backup import test_entity_capture_restore as scenarios


class BackupSelected(Exception):
    """Stop after observing the scenario's history lookup, before restoration."""


@pytest.mark.parametrize(
    "scenario",
    [
        "test_restore_renames_back_and_unhides",
        "test_a_removed_entity_says_what_core_keeps",
    ],
)
async def test_entity_restore_scenario_selects_the_durable_registry_history(
    monkeypatch, scenario
):
    # capture_entity_registry keys history by the registry row's id, which
    # differs from both the helper's name and its renameable entity_id.
    registry_id = "44ca272a46cb46eb850bad205bc54568"
    entry = {"id": registry_id, "hidden": False}

    async def call_tool(name, arguments):
        if name == "ha_get_entity":
            return {"success": True, "entity_entry": entry}
        if name == "ha_get_entity_exposure":
            return {"success": True, "exposed_to": {"conversation": True}}
        assert name in {
            "ha_config_set_helper",
            "ha_set_entity",
            "ha_remove_helpers_integrations",
        }
        return {"success": True}

    client = SimpleNamespace(call_tool=AsyncMock(side_effect=call_tool))
    lookup = AsyncMock(side_effect=BackupSelected)
    monkeypatch.setattr(scenarios, "_wait_for_backup", lookup)
    with pytest.raises(BackupSelected):
        await getattr(scenarios.TestEntityCaptureRestore(), scenario)(
            client, monkeypatch
        )
    lookup.assert_awaited_once_with(
        client, domain="entity_registry", entity_id=registry_id
    )
