"""Main's entity registry contracts through the real Native Core owners."""

import json
from typing import Any

import pytest
from homeassistant.auth.models import User
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.entity_writes import (
    NativeEntityWrites,
)
from ha_mcp.runtime.entities import EntityDiscoveryTools
from ha_mcp.runtime.entity_write_tools import EntityWriteTools
from ha_mcp.tool_api import CallContext, ToolFailure

from ._native_core_backend import backend as backend


async def test_native_entity_read_preserves_core_extended_fields(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create("sensor", "test", "power")
    result = await EntityDiscoveryTools(
        backend, CallContext(hass_admin_user.id)
    ).ha_get_entity(entry.entity_id)
    expected = json.loads(json.dumps(entry.extended_dict))
    assert {key: result["entity_entry"][key] for key in expected} == expected
    assert "enabled" not in result["entity_entry"]
    assert "hidden" not in result["entity_entry"]
    assert "uses_device_name" not in result["entity_entry"]
    assert "full_name" in result["entity_entry"]


async def test_native_registry_wide_settings_keep_the_real_previous_values(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    actor = CallContext(hass_admin_user.id)
    reader = EntityDiscoveryTools(backend, actor)
    writer = EntityWriteTools(
        NativeEntityWrites(hass, actor, authorize=backend.authorize)
    )
    before = await reader.ha_get_entity(exposed_to="conversation")
    changed = await writer.ha_set_entity(
        expose_new_entities={"conversation": not before["expose_new_entities"]},
        entity_id_parts=["device", "entity"],
    )
    assert changed["previous_expose_new_entities"] == {
        "conversation": before["expose_new_entities"]
    }
    assert changed["previous_settings"] == before["settings"]
    after = await reader.ha_get_entity(exposed_to="conversation")
    assert after["expose_new_entities"] is not before["expose_new_entities"]
    assert after["settings"]["entity_id_parts"] == ["device", "entity"]
    restored = await writer.ha_set_entity(
        expose_new_entities=changed["previous_expose_new_entities"],
        entity_id_parts=changed["previous_settings"]["entity_id_parts"] or [],
    )
    assert restored["success"] is True
    assert (await reader.ha_get_entity(exposed_to="conversation"))[
        "settings"
    ] == before["settings"]


async def test_native_auto_rename_uses_core_generated_id_and_keeps_identity(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "sensor", "test", "power", suggested_object_id="old", original_name="Power"
    )
    expected = registry.async_regenerate_entity_id(entry)
    service = NativeEntityWrites(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    )
    result = await service.set(entry.entity_id.title(), new_entity_id="auto")
    actual = registry.async_get(expected)
    assert actual is not None
    assert actual.id == entry.id
    assert result["entity_id"] == expected
    unchanged = await service.set(expected.title(), new_entity_id="auto")
    assert "old_entity_id" not in unchanged


@pytest.mark.parametrize("known", [True, False])
async def test_native_exposure_resolves_real_unregistered_state_before_write(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend, known: bool
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    entity_id = "light.unregistered"
    if known:
        hass.states.async_set(entity_id, "off")
    actor = CallContext(hass_admin_user.id)
    captured: list[dict[str, Any]] = []

    async def capture(payload: dict[str, Any], caller: CallContext) -> None:
        assert caller.user_id == hass_admin_user.id
        captured.append(payload)

    service = NativeEntityWrites(
        hass, actor, authorize=backend.authorize, backup=capture
    )
    if not known:
        with pytest.raises(ToolFailure) as caught:
            await service.set(entity_id, expose_to={"conversation": True})
        assert caught.value.code == "ENTITY_NOT_FOUND"
        assert entity_id not in exposed_entities.async_get_assistant_settings(
            hass, "conversation"
        )
        assert not captured
        return
    result = await service.set(entity_id.title(), expose_to={"conversation": True})
    assert result["entity_id"] == entity_id
    assert result["entity_entry"] is None
    assert captured[0]["current_config"]["preferences"] is None
    row = await EntityDiscoveryTools(backend, actor).ha_get_entity(entity_id.title())
    assert row["entity_entry"] is None
    assert row["exposed_to"] == {"conversation": True}


async def test_native_unknown_assistant_refuses_whole_global_write(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    before = er.async_get(hass).settings
    service = EntityWriteTools(
        NativeEntityWrites(
            hass, CallContext(hass_admin_user.id), authorize=backend.authorize
        )
    )
    with pytest.raises(ToolFailure):
        await service.ha_set_entity(
            expose_new_entities={"unknown-assistant": True},
            entity_id_parts=["device", "entity"],
        )
    assert er.async_get(hass).settings == before


async def test_native_global_partial_failure_preserves_preimages_without_replay(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    actor = CallContext(hass_admin_user.id)
    before = await EntityDiscoveryTools(backend, actor).ha_get_entity(
        exposed_to="conversation"
    )
    original = exposed_entities.ExposedEntities.async_set_expose_new_entities
    calls = 0

    def apply_then_fail(
        owner: exposed_entities.ExposedEntities, assistant: str, value: bool
    ) -> None:
        nonlocal calls
        calls += 1
        original(owner, assistant, value)
        raise HomeAssistantError("save failed after applying preference")

    monkeypatch.setattr(
        exposed_entities.ExposedEntities,
        "async_set_expose_new_entities",
        apply_then_fail,
    )
    service = EntityWriteTools(
        NativeEntityWrites(hass, actor, authorize=backend.authorize)
    )
    with pytest.raises(ToolFailure) as caught:
        await service.ha_set_entity(
            entity_id_parts=["device", "entity"],
            expose_new_entities={
                "conversation": not before["expose_new_entities"],
                "cloud.alexa": True,
            },
        )
    assert caught.value.status == "outcome_unknown"
    assert caught.value.data["previous_settings"] == before["settings"]
    previous_defaults = caught.value.data["previous_expose_new_entities"]
    assert isinstance(previous_defaults, dict)
    assert previous_defaults["conversation"] == before["expose_new_entities"]
    assert caught.value.data["applied"] == ["entity_id_parts"]
    assert calls == 1
    assert (
        await EntityDiscoveryTools(backend, actor).ha_get_entity(
            exposed_to="conversation"
        )
    )["expose_new_entities"] is not before["expose_new_entities"]


async def test_native_reenable_reports_cores_restart_requirement(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "sensor", "test", "disabled", disabled_by=er.RegistryEntryDisabler.USER
    )
    result = await NativeEntityWrites(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    ).set(entry.entity_id, enabled=True)
    actual = registry.async_get(entry.entity_id)
    assert actual is not None
    assert actual.disabled_by is None
    assert result["require_restart"] is True


async def test_native_exposure_chunk_refusal_precedes_every_write(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    hass.states.async_set("light.known", "off")
    before = dict(exposed_entities.async_get_assistant_settings(hass, "conversation"))
    service = NativeEntityWrites(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    )
    with pytest.raises(ToolFailure):
        await service.set(
            ["light.known", "not an id"], expose_to={"conversation": True}
        )
    assert (
        dict(exposed_entities.async_get_assistant_settings(hass, "conversation"))
        == before
    )


async def test_native_exposure_target_disappearing_during_capture_is_not_written(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    entity_id = "light.disappearing"
    hass.states.async_set(entity_id, "off")

    async def capture(payload: dict[str, Any], caller: CallContext) -> None:
        assert caller.user_id == hass_admin_user.id
        assert payload["current_config"]["preferences"] is None
        hass.states.async_remove(entity_id)

    service = NativeEntityWrites(
        hass,
        CallContext(hass_admin_user.id),
        authorize=backend.authorize,
        backup=capture,
    )
    with pytest.raises(ToolFailure):
        await service.set(entity_id, expose_to={"conversation": True})
    assert entity_id not in exposed_entities.async_get_assistant_settings(
        hass, "conversation"
    )
