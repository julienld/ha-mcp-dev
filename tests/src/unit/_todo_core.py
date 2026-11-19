"""Local To-do lists created, persisted and queried through real Core."""

from pathlib import Path
from typing import Any, cast

import pytest
from homeassistant.components.local_todo.const import (
    CONF_STORAGE_KEY,
    CONF_TODO_LIST_NAME,
)
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry, async_capture_events


async def todo_items(hass: HomeAssistant, entity_id: str) -> list[dict[str, Any]]:
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    body = response[entity_id]
    assert isinstance(body, dict)
    rows = body["items"]
    assert isinstance(rows, list)
    return cast("list[dict[str, Any]]", rows)


async def todo_service(
    hass: HomeAssistant, entity_id: str, service: str, **data: Any
) -> None:
    await hass.services.async_call(
        "todo", service, data, target={"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


@pytest.fixture
async def shopping_list(hass: HomeAssistant) -> str:
    await hass.async_add_executor_job(
        Path(hass.config.path(".storage")).mkdir, 0o700, True, True
    )
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup_component(hass, "todo", {})
    entry = MockConfigEntry(
        domain="local_todo",
        title="Shopping",
        data={CONF_STORAGE_KEY: "native-shopping", CONF_TODO_LIST_NAME: "Shopping"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    (registered,) = er.async_entries_for_config_entry(
        er.async_get(hass), entry.entry_id
    )
    entity_id = registered.entity_id
    await todo_service(hass, entity_id, "add_item", item="Milk", due_date="2026-10-23")
    await todo_service(hass, entity_id, "add_item", item="Bread")
    rows = await todo_items(hass, entity_id)
    bread = next(row for row in rows if row["summary"] == "Bread")
    await todo_service(
        hass, entity_id, "update_item", item=bread["uid"], status="completed"
    )
    return entity_id


@pytest.fixture
async def todo_calls(
    hass: HomeAssistant, shopping_list: str
) -> list[Event[dict[str, Any]]]:
    return async_capture_events(hass, EVENT_CALL_SERVICE)


def todo_writes(calls: list[Event[dict[str, Any]]]) -> list[Event[dict[str, Any]]]:
    return [
        event
        for event in calls
        if event.data["domain"] == "todo" and event.data["service"] != "get_items"
    ]
