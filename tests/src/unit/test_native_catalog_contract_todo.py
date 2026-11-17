"""Public Native todo tools use real Local To-do storage, services and actors."""

import copy
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.auth.models import User
from homeassistant.components.local_todo.todo import LocalTodoListEntity
from homeassistant.components.todo import TodoItem
from homeassistant.components.todo import entity as todo_entity
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.client.rest_client import HomeAssistantClient
from ha_mcp.config import get_global_settings
from ha_mcp.runtime import Engine
from ha_mcp.tool_api import CallContext, ToolFailure
from ha_mcp.tools.tools_todo import TodoTools

from ._native_test_engine import native_engine
from ._todo_core import shopping_list as shopping_list
from ._todo_core import todo_calls as todo_calls
from ._todo_core import todo_items, todo_service, todo_writes

_NAMES = {"ha_get_todo", "ha_set_todo_item", "ha_remove_todo_item"}


def _engine(hass: HomeAssistant, backup: Any = None) -> Engine:
    return native_engine(
        NativeBackend(hass, todo_backup=backup or AsyncMock(return_value={})), _NAMES
    )


async def test_native_todo_reads_core_items_and_filter_without_transport(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
) -> None:
    hass.states.async_set("sensor.unrelated", "0")
    expected = await todo_items(hass, shopping_list)
    engine = _engine(hass)
    actor = CallContext(hass_admin_user.id)
    lists = await engine.call("ha_get_todo", {}, actor)
    assert not lists.is_error, lists.data
    assert {row["entity_id"] for row in lists.data["todo_lists"]} == {shopping_list}
    (listed,) = [
        row for row in lists.data["todo_lists"] if row["entity_id"] == shopping_list
    ]
    state = hass.states.get(shopping_list)
    assert state is not None
    assert listed["friendly_name"] == state.attributes["friendly_name"]
    assert listed["supported_features"] == state.attributes["supported_features"]
    result = await engine.call(
        "ha_get_todo", {"entity_id": shopping_list, "status": "needs_action"}, actor
    )
    assert not result.is_error, result.data
    assert result.data["items"] == [
        row for row in expected if row["status"] == "needs_action"
    ]
    assert todo_writes(todo_calls) == []


async def test_native_todo_add_keeps_the_actual_actor_and_persisted_row(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
) -> None:
    backup = AsyncMock(return_value={})
    result = await _engine(hass, backup).call(
        "ha_set_todo_item",
        {
            "entity_id": shopping_list,
            "summary": "Coffee",
            "description": "Beans",
            "due_datetime": "2026-10-24T12:00:00+00:00",
        },
        CallContext(hass_admin_user.id),
    )
    assert not result.is_error, result.data
    rows = await todo_items(hass, shopping_list)
    stored = next(row for row in rows if row["summary"] == "Coffee")
    assert result.data["todo_item"] == stored
    (call,) = todo_writes(todo_calls)
    assert call.data["service"] == "add_item"
    assert call.context.user_id == hass_admin_user.id
    assert stored["description"] == "Beans"
    assert datetime.fromisoformat(stored["due"]) == datetime.fromisoformat(
        "2026-10-24T12:00:00+00:00"
    )
    backup.assert_not_awaited()


async def test_missing_core_serializer_refuses_before_mutation(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (milk,) = [
        row for row in await todo_items(hass, shopping_list) if row["summary"] == "Milk"
    ]
    with monkeypatch.context() as patcher:
        patcher.delattr(todo_entity, "api_items_factory")
        result = await _engine(hass).call(
            "ha_set_todo_item",
            {"entity_id": shopping_list, "item": milk["uid"], "status": "completed"},
            CallContext(hass_admin_user.id),
        )
    assert result.is_error and result.status == "not_started"
    assert result.data["error"]["code"] == "UNSUPPORTED_OPERATION"
    assert todo_writes(todo_calls) == []
    assert milk in await todo_items(hass, shopping_list)


@pytest.mark.parametrize("remove", [False, True])
async def test_native_todo_updates_and_deletes_capture_once_before_dispatch(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    remove: bool,
) -> None:
    milk = next(
        row for row in await todo_items(hass, shopping_list) if row["summary"] == "Milk"
    )
    captures: list[dict[str, Any]] = []

    async def capture(payload: dict[str, Any], actor: CallContext) -> dict[str, Any]:
        assert todo_writes(todo_calls) == [] and actor.user_id == hass_admin_user.id
        captures.append(copy.deepcopy(payload))
        return {"warnings": ["Snapshot could not be persisted"]}

    tool = "ha_remove_todo_item" if remove else "ha_set_todo_item"
    result = await _engine(hass, capture).call(
        tool,
        {
            "entity_id": shopping_list,
            "item": milk["uid"],
            **({} if remove else {"status": "completed"}),
        },
        CallContext(hass_admin_user.id),
    )
    assert not result.is_error, result.data
    assert captures == [
        {
            "entity_id": shopping_list,
            "item": milk["uid"],
            "source_tool": tool,
            "current_item": milk,
        }
    ]
    assert "Snapshot could not be persisted" in result.data["warnings"]
    (call,) = todo_writes(todo_calls)
    assert call.data["service"] == ("remove_item" if remove else "update_item")
    rows = await todo_items(hass, shopping_list)
    assert (
        not any(row["uid"] == milk["uid"] for row in rows)
        if remove
        else any(
            row["uid"] == milk["uid"] and row["status"] == "completed" for row in rows
        )
    )


@pytest.mark.parametrize("wrong_domain", [False, True])
async def test_invalid_mutations_never_capture_or_dispatch(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    wrong_domain: bool,
) -> None:
    backup = AsyncMock(return_value={})
    arguments = (
        {"entity_id": "light.wrong", "summary": "Invalid"}
        if wrong_domain
        else {"entity_id": shopping_list, "item": " ", "status": "completed"}
    )
    result = await _engine(hass, backup).call(
        "ha_set_todo_item", arguments, CallContext(hass_admin_user.id)
    )
    assert result.is_error
    assert todo_writes(todo_calls) == []
    backup.assert_not_awaited()


@pytest.mark.parametrize(
    "fields",
    [
        {"due_date": "2026-10-31", "due_datetime": "2026-10-31T12:00:00+00:00"},
        {"due_date": "not-a-date"},
    ],
)
async def test_core_refuses_invalid_fields_without_changing_the_list(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    fields: dict[str, str],
) -> None:
    before = await todo_items(hass, shopping_list)
    result = await _engine(hass).call(
        "ha_set_todo_item",
        {"entity_id": shopping_list, "summary": "Date", **fields},
        CallContext(hass_admin_user.id),
    )
    assert result.is_error and result.status == "not_started", result.data
    assert todo_writes(todo_calls) == []
    assert await todo_items(hass, shopping_list) == before


async def test_readonly_still_lists_but_never_starts_writes(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
) -> None:
    engine = _engine(hass)
    engine.read_only = True
    actor = CallContext(hass_admin_user.id)
    assert not (await engine.call("ha_get_todo", {}, actor)).is_error
    with pytest.raises(ToolFailure, match="Writes are disabled"):
        await engine.call(
            "ha_set_todo_item", {"entity_id": shopping_list, "summary": "Milk"}, actor
        )
    assert todo_writes(todo_calls) == []


@pytest.mark.parametrize("revoke", [False, True])
async def test_live_policy_and_credentials_are_rechecked_after_snapshot(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    revoke: bool,
) -> None:
    async def capture(payload: dict[str, Any], actor: CallContext) -> dict[str, Any]:
        if revoke:
            await hass.auth.async_update_user(hass_admin_user, group_ids=[])
        else:
            engine.read_only = True
        return {}

    engine = _engine(hass, capture)
    milk = next(
        row for row in await todo_items(hass, shopping_list) if row["summary"] == "Milk"
    )
    result = await engine.call(
        "ha_set_todo_item",
        {"entity_id": shopping_list, "item": milk["uid"], "status": "completed"},
        CallContext(hass_admin_user.id),
    )
    assert result.is_error and todo_writes(todo_calls) == []
    assert milk in await todo_items(hass, shopping_list)


@pytest.mark.parametrize(
    "failure", [HomeAssistantError, ServiceValidationError, ValueError]
)
async def test_provider_failure_after_a_real_effect_is_uncertain_and_not_replayed(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    failure: type[Exception],
) -> None:
    create = LocalTodoListEntity.async_create_todo_item
    listeners = hass.bus.async_listeners().get("state_changed", 0)

    async def create_then_fail(entity: LocalTodoListEntity, item: TodoItem) -> None:
        await create(entity, item)
        raise failure("Provider failed after persisting the item")

    monkeypatch.setattr(LocalTodoListEntity, "async_create_todo_item", create_then_fail)
    result = await _engine(hass).call(
        "ha_set_todo_item",
        {"entity_id": shopping_list, "summary": "Persisted once"},
        CallContext(hass_admin_user.id),
    )
    assert result.is_error and result.status == "outcome_unknown", result.data
    assert result.data["error"]["code"] == "OUTCOME_UNKNOWN"
    assert len(todo_writes(todo_calls)) == 1
    rows = await todo_items(hass, shopping_list)
    assert len([row for row in rows if row["summary"] == "Persisted once"]) == 1
    assert hass.bus.async_listeners().get("state_changed", 0) == listeners


async def test_change_during_snapshot_is_refused_without_dispatch(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
) -> None:
    milk = next(
        row for row in await todo_items(hass, shopping_list) if row["summary"] == "Milk"
    )

    async def capture(payload: dict[str, Any], actor: CallContext) -> dict[str, Any]:
        await todo_service(
            hass,
            shopping_list,
            "update_item",
            item=milk["uid"],
            rename="Changed externally",
        )
        return {}

    result = await _engine(hass, capture).call(
        "ha_remove_todo_item",
        {"entity_id": shopping_list, "item": "Milk"},
        CallContext(hass_admin_user.id),
    )
    assert result.is_error and result.status == "not_started", result.data
    assert result.data["error"]["code"] == "CONFIG_CONFLICT"
    assert [event.data["service"] for event in todo_writes(todo_calls)] == [
        "update_item"
    ]
    assert any(
        row["uid"] == milk["uid"] for row in await todo_items(hass, shopping_list)
    )


async def test_uid_summary_collision_is_refused_before_snapshot(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    core_client: HomeAssistantClient,
) -> None:
    milk = next(
        row for row in await todo_items(hass, shopping_list) if row["summary"] == "Milk"
    )
    await todo_service(hass, shopping_list, "add_item", item=milk["uid"])
    collision = next(
        row
        for row in await todo_items(hass, shopping_list)
        if row["summary"] == milk["uid"]
    )
    reply = await core_client.send_websocket_message(
        {
            "type": "todo/item/move",
            "entity_id": shopping_list,
            "uid": collision["uid"],
        }
    )
    assert reply["success"], reply
    assert (await todo_items(hass, shopping_list))[0]["uid"] == collision["uid"]
    writes_before = len(todo_writes(todo_calls))
    backup = AsyncMock(return_value={})
    result = await _engine(hass, backup).call(
        "ha_remove_todo_item",
        {"entity_id": shopping_list, "item": "Milk"},
        CallContext(hass_admin_user.id),
    )
    assert result.is_error and result.status == "not_started", result.data
    assert result.data["error"]["code"] == "CONFIG_CONFLICT"
    assert len(todo_writes(todo_calls)) == writes_before
    backup.assert_not_awaited()


async def test_original_uid_stays_pinned_when_summary_is_reused_during_snapshot(
    hass: HomeAssistant,
    hass_admin_user: User,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    core_client: HomeAssistantClient,
) -> None:
    milk = next(
        row for row in await todo_items(hass, shopping_list) if row["summary"] == "Milk"
    )

    async def capture(payload: dict[str, Any], actor: CallContext) -> dict[str, Any]:
        await todo_service(hass, shopping_list, "add_item", item="Milk")
        new = next(
            row
            for row in await todo_items(hass, shopping_list)
            if row["summary"] == "Milk" and row["uid"] != milk["uid"]
        )
        reply = await core_client.send_websocket_message(
            {
                "type": "todo/item/move",
                "entity_id": shopping_list,
                "uid": new["uid"],
            }
        )
        assert reply["success"], reply
        assert (await todo_items(hass, shopping_list))[0]["uid"] == new["uid"]
        return {}

    result = await _engine(hass, capture).call(
        "ha_remove_todo_item",
        {"entity_id": shopping_list, "item": "Milk"},
        CallContext(hass_admin_user.id),
    )
    assert not result.is_error, result.data
    rows = await todo_items(hass, shopping_list)
    assert not any(row["uid"] == milk["uid"] for row in rows)
    assert len([row for row in rows if row["summary"] == "Milk"]) == 1
    assert [event.data["service"] for event in todo_writes(todo_calls)] == [
        "add_item",
        "remove_item",
    ]


async def test_legacy_facade_keeps_core_routes_and_updates_the_real_list(
    hass: HomeAssistant,
    core_client: HomeAssistantClient,
    shopping_list: str,
    todo_calls: list[Event[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_global_settings(), "enable_auto_backup", False)
    tools = TodoTools(core_client)
    rows = await todo_items(hass, shopping_list)
    read = await tools.ha_get_todo(entity_id=shopping_list, status="completed")
    assert read["items"] == [row for row in rows if row["status"] == "completed"]
    milk = next(row for row in rows if row["summary"] == "Milk")
    result = await tools.ha_set_todo_item(
        entity_id=shopping_list, item=milk["uid"], status="completed"
    )
    assert result["success"] is True
    assert any(
        row["uid"] == milk["uid"] and row["status"] == "completed"
        for row in await todo_items(hass, shopping_list)
    )
    assert [event.data["service"] for event in todo_writes(todo_calls)] == [
        "update_item"
    ]
