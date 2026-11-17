"""The live authoring scenario must use the currently advertised tool inputs."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from jsonschema import validate

from ha_mcp.runtime.catalog import define_tool
from ha_mcp.runtime.config_reads import AutomationReadTools
from ha_mcp.runtime.config_removals import AutomationRemovalTools
from tests.native import configuration_checks


async def test_configuration_scenario_can_read_and_remove_its_created_automation(
    monkeypatch,
):
    contracts = {
        name: define_tool(Mock(), owner, name, annotations={}).input_schema
        for name, owner in (
            ("ha_config_get_automation", AutomationReadTools),
            ("ha_config_remove_automation", AutomationRemovalTools),
        )
    }
    script = {}
    automation_id = "automation.created_by_scenario"
    visited = []

    async def call(name, arguments):
        if name in contracts:
            validate(arguments, contracts[name])
            assert arguments["entity_id"] == automation_id
            visited.append(name)
        if name == "ha_config_set_script":
            if "config" in arguments:
                script.update(deepcopy(arguments["config"]))
            if "python_transform" in arguments:
                script["description"] = "Native transform"
        if name == "ha_config_get_script":
            return {"config": deepcopy(script), "config_hash": "before-transform"}
        return {
            "success": True,
            "activated": True,
            "actions_triggered": True,
            "automation_id": automation_id,
            "config": {"alias": "Native contract automation"},
        }

    checks = SimpleNamespace(call=call, passed=Mock())
    for helper in ("expect_state", "exercise_traces", "exercise_snapshot_panel"):
        monkeypatch.setattr(configuration_checks, helper, AsyncMock())
    await configuration_checks.exercise_configuration(checks, {}, "http://fixture")
    assert visited == list(contracts)
