"""A failed inline-resource E2E must release its disposable resource and backup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.src.e2e.workflows.auto_backup import test_resource_capture_restore as lane


@pytest.mark.parametrize("failure_step", ["backup", "verification"])
async def test_inline_resource_failure_still_cleans_recovery_and_resource(
    monkeypatch, failure_step
):
    failure = AssertionError("Workflow failure")
    client = object()
    safe_call = AsyncMock(return_value={"resource_id": "disposable-resource"})
    cleanup_backup = AsyncMock()
    call = AsyncMock(side_effect=[{}, {"success": True}, failure])
    monkeypatch.setattr(lane, "safe_call_tool", safe_call)
    monkeypatch.setattr(lane, "_delete_leftover_backup", cleanup_backup)
    monkeypatch.setattr(lane, "_enable_auto_backup", lambda _: None)
    monkeypatch.setattr(lane, "_HA_PROPAGATION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(
        lane, "MCPAssertions", lambda _: SimpleNamespace(call_tool_success=call)
    )
    monkeypatch.setattr(
        lane,
        "_wait_for_backup",
        AsyncMock(
            side_effect=failure if failure_step == "backup" else None,
            return_value="disposable-backup",
        ),
    )

    with pytest.raises(AssertionError) as caught:
        await lane.TestDashboardResourceCaptureRestore().test_inline_dashboard_resource_full_loop(
            client, monkeypatch
        )

    assert caught.value is failure
    cleanup_backup.assert_awaited_once_with(
        client, None if failure_step == "backup" else "disposable-backup"
    )
    assert safe_call.await_args_list[-1].args == (
        client,
        "ha_config_delete_dashboard_resource",
        {"resource_id": "disposable-resource"},
    )
