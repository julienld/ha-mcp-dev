"""The current entity-restore E2E story must verify effects, not an ACK."""

import copy

import pytest

from ..e2e.workflows.auto_backup import test_capture_and_restore as backup_helpers
from ..e2e.workflows.auto_backup import test_entity_capture_restore as scenarios


class RegistryBackupClient:
    def __init__(self, *, capture=True, apply_restore=True):
        self.entry = None
        self.exposed = True
        self.capture = capture
        self.apply_restore = apply_restore
        self.registry_id = "owned-registry-identity"
        self.restores = []
        self.backups = {
            "prior.yaml": {"domain": "entity", "entity_id": "light.unowned"}
        }
        self.baseline = copy.deepcopy(self.backups)
        self.images = {}
        self.sequence = 0

    def snapshot(self):
        self.sequence += 1
        name = f"capture-{self.sequence}.yaml"
        self.backups[name] = {"domain": "entity", "entity_id": self.entry["entity_id"]}
        self.images[name] = (copy.deepcopy(self.entry), self.exposed)
        return name

    async def send_websocket_message(self, message):
        assert message["type"] == "config/entity_registry/get"
        assert message["entity_id"] == self.entry["entity_id"]
        return {"success": True, "result": {"id": self.registry_id}}

    async def call_tool(self, tool, arguments):
        if tool == "ha_config_set_helper":
            self.entry = {
                "entity_id": f"input_boolean.{arguments['name']}",
                "hidden": False,
                "hidden_by": None,
            }
            return {"success": True}
        if tool == "ha_get_entity":
            if self.entry is None or arguments["entity_id"] != self.entry["entity_id"]:
                return {
                    "success": False,
                    "error": {
                        "code": "ENTITY_NOT_FOUND",
                        "message": "Entity not found",
                    },
                }
            return {"success": True, "entity_entry": copy.deepcopy(self.entry)}
        if tool == "ha_get_entity_exposure":
            assert arguments["entity_id"] == self.entry["entity_id"]
            return {"success": True, "exposed_to": {"conversation": self.exposed}}
        if tool == "ha_set_entity":
            assert arguments["entity_id"] == self.entry["entity_id"]
            if self.capture:
                self.snapshot()
            self.entry.update(
                entity_id=arguments["new_entity_id"],
                hidden=arguments["hidden"],
                hidden_by="user",
            )
            self.exposed = arguments["expose_to"]["conversation"]
            return {"success": True}
        if tool == "ha_remove_helpers_integrations":
            if (
                self.entry is not None
                and arguments["target"] == self.entry["entity_id"]
            ):
                self.entry = None
            return {"success": True}
        assert tool == "ha_manage_backup"
        return self._backup_tool(arguments)

    def _backup_tool(self, arguments):
        action = arguments["action"]
        if action == "list":
            return {
                "success": True,
                "data": {
                    "backups": [
                        {"name": name, **record}
                        for name, record in self.backups.items()
                        if record["domain"] == arguments["domain"]
                        and record["entity_id"] == arguments["entity_id"]
                    ]
                },
            }
        name = arguments["backup_name"]
        if action == "restore":
            self.restores.append(name)
            safety = self.snapshot()
            if self.apply_restore:
                entry, exposed = self.images[name]
                self.entry, self.exposed = copy.deepcopy(entry), exposed
            return {"success": True, "data": {"safety_backup": safety, "result": {}}}
        assert action == "delete"
        del self.backups[name]
        return {"success": True}


@pytest.fixture(autouse=True)
def bound_poll_window(monkeypatch):
    original = scenarios.wait_for_tool_result

    async def wait(*args, **kwargs):
        return await original(
            *args, **{**kwargs, "timeout": 0.01, "poll_interval": 0.001}
        )

    monkeypatch.setattr(scenarios, "wait_for_tool_result", wait)
    monkeypatch.setattr(backup_helpers, "wait_for_tool_result", wait)


async def scenario(client, monkeypatch):
    try:
        await (
            scenarios.TestEntityCaptureRestore().test_restore_renames_back_and_unhides(
                client, client, monkeypatch
            )
        )
    except pytest.skip.Exception as error:
        pytest.fail(f"A registry capture defect was hidden as a skip: {error}")


async def test_registry_backup_scenario_restores_then_cleans_only_its_objects(
    monkeypatch,
):
    client = RegistryBackupClient()
    await scenario(client, monkeypatch)
    assert client.entry is None
    assert len(client.restores) == 1
    assert client.backups["prior.yaml"] == client.baseline["prior.yaml"]


async def test_missing_registry_capture_fails_and_cleans_the_owned_entity(monkeypatch):
    client = RegistryBackupClient(capture=False)
    with pytest.raises(TimeoutError):
        await scenario(client, monkeypatch)
    assert client.entry is None
    assert not client.restores
    assert client.backups == client.baseline


async def test_successful_restore_ack_without_registry_effect_is_rejected(monkeypatch):
    client = RegistryBackupClient(apply_restore=False)
    with pytest.raises(AssertionError, match="ha_get_entity"):
        await scenario(client, monkeypatch)
    assert client.entry is None
    assert len(client.restores) == 1, "An unconfirmed restore was replayed"
    assert client.backups["prior.yaml"] == client.baseline["prior.yaml"]
