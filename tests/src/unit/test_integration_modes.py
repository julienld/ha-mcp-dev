"""Integration mode forwarding and the confirmation-before-backup contract."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.tools.tools_integrations import IntegrationTools


async def test_remote_integration_write_waits_for_restore_admission_even_without_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Lock()
    await gate.acquire()
    client = MagicMock(
        get_config_entry=AsyncMock(
            return_value={"entry_id": "entry", "domain": "demo"}
        ),
        send_websocket_message=AsyncMock(
            return_value={"success": True, "result": {"require_restart": False}}
        ),
    )
    monkeypatch.setattr(
        "ha_mcp.tools.tools_integrations.entry_write_guard", lambda *_args: gate
    )
    call = asyncio.create_task(
        IntegrationTools(client).ha_set_integration(entry_id="entry", enabled=False)
    )
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not call.done()
        client.send_websocket_message.assert_not_awaited()
    finally:
        gate.release()
    result = await asyncio.wait_for(call, 2)
    assert result["success"]
    client.send_websocket_message.assert_awaited_once()


class TestSetIntegrationModes:
    """Unit tests for ha_set_integration mode routing (issue #1814).

    The three modes — enable/disable, add (config flow), update options
    (options flow) — are mutually exclusive; the flow drivers themselves
    are covered by test_flow_error_parsing and the e2e suite, so these
    tests pin only the routing and parameter-validation layer.
    """

    @pytest.fixture
    def mock_client(self):
        client = MagicMock(get_config_entry=AsyncMock(return_value={"domain": "hue"}))
        client.send_websocket_message = AsyncMock(
            return_value={"success": True, "result": {"require_restart": False}}
        )
        client.start_config_flow = AsyncMock()
        client.start_options_flow = AsyncMock()
        return client

    @pytest.fixture
    def tools(self, mock_client):
        return IntegrationTools(mock_client)

    async def _assert_invalid(self, coro, fragment: str):
        with pytest.raises(ToolError) as exc_info:
            _ = await coro
        err = json.loads(str(exc_info.value))
        assert err["success"] is False
        assert err["error"]["code"] == "VALIDATION_INVALID_PARAMETER"
        assert fragment in err["error"]["message"], err["error"]["message"]

    # === Mutual exclusion ===

    async def test_domain_and_entry_id_rejected(self, tools, mock_client):
        await self._assert_invalid(
            tools.ha_set_integration(entry_id="abc", domain="hue"),
            "not both",
        )
        mock_client.start_config_flow.assert_not_called()
        mock_client.send_websocket_message.assert_not_called()

    async def test_enabled_and_domain_rejected(self, tools, mock_client):
        await self._assert_invalid(
            tools.ha_set_integration(domain="hue", enabled=True),
            "mutually exclusive",
        )
        mock_client.start_config_flow.assert_not_called()

    async def test_enabled_and_config_rejected(self, tools, mock_client):
        await self._assert_invalid(
            tools.ha_set_integration(entry_id="abc", enabled=True, config={"x": 1}),
            "mutually exclusive",
        )
        mock_client.send_websocket_message.assert_not_called()
        mock_client.start_options_flow.assert_not_called()

    # === Nothing-to-do guards ===

    async def test_no_arguments_rejected(self, tools):
        await self._assert_invalid(tools.ha_set_integration(), "Nothing to do")

    @pytest.mark.parametrize(
        ("name", "value"),
        [("expected_device_id", "device-1"), ("expected_unique_id", "unique-1")],
    )
    async def test_reconfigure_only_parameters_rejected_outside_reconfigure_mode(
        self, tools, name, value
    ):
        """The identity guards must not ride an unguarded options update."""
        with (
            patch(
                "ha_mcp.runtime.integration_writes.run_integration_step",
                new=AsyncMock(return_value={"success": True}),
            ) as options_mock,
            pytest.raises(ToolError) as exc_info,
        ):
            await tools.ha_set_integration(
                entry_id="abc", config={"scan_interval": 30}, **{name: value}
            )

        err = json.loads(str(exc_info.value))
        assert err["error"]["code"] == "VALIDATION_INVALID_PARAMETER"
        assert "reconfigure" in err["error"]["message"].lower()
        assert err["rejected_parameters"] == [name]
        options_mock.assert_not_awaited()

    async def test_set_integration_has_explicit_safety_annotations(self, tools):
        """The unified tool advertises its state-changing safety semantics."""
        annotations = tools.ha_set_integration.__fastmcp__.annotations
        assert annotations.open_world_hint is False
        assert annotations.destructive_hint is True
        assert annotations.read_only_hint is False
        assert annotations.idempotent_hint is False

    # === Mode delegation ===

    @pytest.mark.parametrize(
        ("call", "expected"),
        [
            pytest.param(
                {"domain": "Workday ", "config": {"name": "Workday"}},
                {"domain": "workday", "entry_id": None, "config": {"name": "Workday"}},
                id="add",
            ),
            pytest.param(
                {"domain": "sun"},
                {"domain": "sun", "entry_id": None, "config": None},
                id="add-without-config",
            ),
            pytest.param(
                {"domain": "knx", "flow_id": "f1", "menu_choice": "tunnel"},
                {
                    "domain": "knx",
                    "entry_id": None,
                    "flow_id": "f1",
                    "menu_choice": "tunnel",
                },
                id="add-continue-menu",
            ),
            pytest.param(
                {"entry_id": "abc", "config": {"scan_interval": 30}},
                {"domain": None, "entry_id": "abc", "config": {"scan_interval": 30}},
                id="options",
            ),
            pytest.param(
                {"entry_id": "abc", "flow_id": "f1", "abort": True},
                {"domain": None, "entry_id": "abc", "flow_id": "f1", "abort": True},
                id="options-abort",
            ),
            pytest.param(
                {"entry_id": "abc"},
                {"domain": None, "entry_id": "abc"},
                id="options-first-step",
            ),
            pytest.param(
                {
                    "entry_id": "abc",
                    "reconfigure": True,
                    "config": {"host": "192.0.2.170"},
                    "expected_device_id": "device-1",
                },
                {
                    "domain": None,
                    "entry_id": "abc",
                    "config": {"host": "192.0.2.170"},
                    "expected_identity": {
                        "device_id": "device-1",
                        "unique_id": None,
                        "mac": None,
                        "entity_ids": [],
                    },
                },
                id="reconfigure",
            ),
            pytest.param(
                {
                    "entry_id": "abc",
                    "reconfigure": True,
                    "flow_id": "f1",
                    "menu_choice": "advanced",
                    "abort": True,
                    "expected_device_id": "device-1",
                    "expected_unique_id": "uid",
                    "expected_mac": "AA:BB",
                    "expected_entity_ids": ["switch.x"],
                },
                {
                    "domain": None,
                    "entry_id": "abc",
                    "flow_id": "f1",
                    "menu_choice": "advanced",
                    "abort": True,
                    "expected_identity": {
                        "device_id": "device-1",
                        "unique_id": "uid",
                        "mac": "AA:BB",
                        "entity_ids": ["switch.x"],
                    },
                },
                id="reconfigure-every-argument",
            ),
        ],
    )
    async def test_add_and_options_modes_delegate_to_run_integration_step(
        self, tools, mock_client, call, expected
    ):
        """One step per call: domain (setup) and entry_id (options) both go
        through run_integration_step; the unset parameters stay unset."""
        sentinel = {"success": True, "flow_id": "f1"}
        with patch(
            "ha_mcp.runtime.integration_writes.run_integration_step",
            new=AsyncMock(return_value=sentinel),
        ) as step_mock:
            result = await tools.ha_set_integration(**call)

        step_mock.assert_awaited_once_with(
            step_mock.await_args.args[0],
            **{
                "flow_id": None,
                "config": None,
                "menu_choice": None,
                "abort": False,
                **expected,
            },
        )
        assert result is sentinel

    async def test_enable_disable_mode_still_works(self, tools, mock_client):
        result = await tools.ha_set_integration(entry_id="abc", enabled=False)
        assert result["success"] is True
        assert result["entry_id"] == "abc"
        assert result["require_restart"] is False
        mock_client.send_websocket_message.assert_awaited_once_with(
            {
                "type": "config_entries/disable",
                "entry_id": "abc",
                "disabled_by": "user",
            }
        )

    async def test_enable_mode_sends_disabled_by_none(self, tools, mock_client):
        result = await tools.ha_set_integration(entry_id="abc", enabled=True)
        assert result["success"] is True
        mock_client.send_websocket_message.assert_awaited_once_with(
            {
                "type": "config_entries/disable",
                "entry_id": "abc",
                "disabled_by": None,
            }
        )
