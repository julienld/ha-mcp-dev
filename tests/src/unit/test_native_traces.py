"""Native trace reads on real Core stores, registries and authenticated users."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from homeassistant.auth.models import User
from homeassistant.components.trace import util as trace_util
from homeassistant.components.trace.const import DATA_TRACE_STORE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.json import ExtendedJSONEncoder
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.traces import NativeTraces
from ha_mcp.runtime.trace_tools import TraceFacade
from ha_mcp.tool_api import CallContext, ToolFailure, UnsupportedOperation

from ._trace_fixtures import automation_run, script_run, store_runs


@pytest.fixture
async def traces(hass: HomeAssistant, hass_admin_user: User) -> NativeTraces:
    assert await async_setup_component(hass, "trace", {})
    er.async_get(hass).async_get_or_create(
        "automation", "automation", "stable-id", suggested_object_id="renamed"
    )
    return NativeTraces(
        hass, CallContext(hass_admin_user.id), authorize=NativeBackend(hass).authorize
    )


async def test_trace_list_uses_registry_identity_and_core_timestamp_paging(
    hass: HomeAssistant,
    traces: NativeTraces,
) -> None:
    for index in range(5):
        with freeze_time(f"2026-11-08T16:00:0{index}+00:00"):
            await store_runs(
                hass,
                automation_run(
                    str(index), context_id=f"ctx-{index}", item_id="stable-id"
                ),
            )
    progress = AsyncMock()
    traces.actor = CallContext(traces.actor.user_id, read_only=True, progress=progress)
    result = await TraceFacade(traces.get).ha_get_automation_traces(
        entity_id="automation.renamed", limit=2, offset=1
    )
    assert [row["run_id"] for row in result["traces"]] == ["3", "2"]
    assert result["total_available"] == 5 and result["has_more"]
    assert [call.kwargs["progress"] for call in progress.await_args_list] == [0, 1, 3]


async def test_detail_preserves_cores_extended_dict_and_variable_values(
    hass: HomeAssistant,
    traces: NativeTraces,
) -> None:
    run = automation_run(
        "run",
        context_id="ctx",
        item_id="stable-id",
        changed_variables={"when": datetime(2026, 11, 8, tzinfo=UTC)},
    )
    await store_runs(hass, run)
    expected = json.loads(
        json.dumps(
            await trace_util.async_get_trace(hass, "automation.stable-id", "run"),
            cls=ExtendedJSONEncoder,
        )
    )
    result = await traces.get(
        entity_id="automation.renamed", run_id="run", sections="trace,config,context"
    )
    for key in ("trace", "config", "context"):
        assert result[key] == expected[key]
    assert "action_trace" not in result and "config_summary" not in result


async def test_domain_lists_include_each_core_item_without_an_entity_selector(
    hass: HomeAssistant,
    traces: NativeTraces,
) -> None:
    await store_runs(
        hass,
        automation_run("a", context_id="ctx-a"),
        automation_run("b", context_id="ctx-b", item_id="other"),
    )
    result = await traces.get(domain="automation")
    assert {row["item_id"] for row in result["traces"]} == {"uid_1", "other"}
    assert "entity_id" not in result


async def test_context_resolves_actual_core_run_and_filters_other_domains(
    hass: HomeAssistant,
    traces: NativeTraces,
) -> None:
    await store_runs(
        hass,
        automation_run("a", context_id="ctx-a", parent_id="cause"),
        script_run("s", context_id="ctx-s", parent_id="cause"),
    )
    result = await traces.get(domain="script", context_id="cause", sections="context")
    assert result["run_id"] == "s" and result["item_id"] == "uid_2"
    assert result["context_match"] == "parent"
    assert result["context"]["parent_id"] == "cause"


@pytest.mark.parametrize("storage", [5, 0])
async def test_idle_script_diagnostics_read_core_configuration(
    hass: HomeAssistant,
    traces: NativeTraces,
    storage: int,
) -> None:
    assert await async_setup_component(
        hass,
        "script",
        {
            "script": {
                "idle": {
                    "sequence": [{"event": "native_trace_probe"}],
                    "trace": {"stored_traces": storage},
                }
            }
        },
    )
    await hass.async_block_till_done()
    result = await traces.get(entity_id="script.idle")
    diagnostics = result["diagnostics"]
    assert diagnostics["entity_exists"] and diagnostics["entity_enabled"]
    assert diagnostics["trace_storage_enabled"] is (storage > 0)
    assert "disabled (state off)" not in diagnostics["suggestion"]
    if storage == 0:
        assert "stored_traces: 0" in diagnostics["suggestion"]


async def test_missing_entity_diagnostic_uses_main_contract(
    traces: NativeTraces,
) -> None:
    result = await traces.get(entity_id="script.missing")
    assert result["diagnostics"]["entity_exists"] is False
    assert "automation_exists" not in result["diagnostics"]


async def test_missing_storage_is_explicitly_unsupported(
    hass: HomeAssistant,
    traces: NativeTraces,
) -> None:
    del hass.data[DATA_TRACE_STORE]
    with pytest.raises(UnsupportedOperation):
        await traces.get(entity_id="automation.renamed", run_id="missing")


async def test_missing_run_keeps_core_failure_visible(traces: NativeTraces) -> None:
    with pytest.raises(ToolFailure, match="trace could not be found") as raised:
        await traces.get(entity_id="automation.renamed", run_id="missing")
    assert raised.value.status == "not_started"


async def test_revocation_after_formatting_prevents_disclosing_private_trace(
    hass: HomeAssistant,
    hass_admin_user: User,
    traces: NativeTraces,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await store_runs(
        hass,
        automation_run(
            "private-run", context_id="private-context", item_id="stable-id"
        ),
    )
    execute = hass.async_add_executor_job

    async def revoke(function: Callable[..., Any], *args: Any) -> Any:
        result = await execute(function, *args)
        hass_admin_user.is_active = False
        return result

    monkeypatch.setattr(hass, "async_add_executor_job", revoke)
    with pytest.raises(ToolFailure) as raised:
        await traces.get(entity_id="automation.renamed")
    assert raised.value.code == "AUTH_FORBIDDEN"
    assert "private-run" not in str(raised.value)


async def test_cancellation_drains_issued_core_restore_io(
    hass: HomeAssistant,
    traces: NativeTraces,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = trace_util.async_list_traces

    async def delayed(*args: Any) -> Any:
        started.set()
        await release.wait()
        result = await original(*args)
        drained.set()
        return result

    monkeypatch.setattr(trace_util, "async_list_traces", delayed)
    task = asyncio.create_task(traces.get(entity_id="automation.renamed"))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert drained.is_set()
