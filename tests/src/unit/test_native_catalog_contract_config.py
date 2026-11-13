"""Persisted Native configuration reads use real Core views, locks and files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.core_views import config_view
from ha_mcp.runtime.config_reads import (
    AutomationReadTools,
    SceneReadTools,
    ScriptReadTools,
)
from ha_mcp.tool_api import CallContext, UnsupportedOperation

from ._native_core_backend import backend as backend


def _persist(hass: HomeAssistant, filename: str, value: Any) -> None:
    path = Path(hass.config.path(filename))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value), encoding="utf-8")


async def test_native_config_uses_fresh_owner_content_and_hashes_before_category(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    current = [{"id": "uid", "alias": "Before", "action": [{"delay": 1}]}]
    _persist(hass, "automations.yaml", current)
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "automation", "automation", "uid", suggested_object_id="current"
    )
    registry.async_update_entity(entry.entity_id, categories={"automation": "one"})
    tools = AutomationReadTools(backend, CallContext(hass_admin_user.id))
    first = await tools.ha_config_get_automation(entity_id="uid")
    current[0]["alias"] = "After"
    _persist(hass, "automations.yaml", current)
    second = await tools.ha_config_get_automation(entity_id="uid")
    registry.async_update_entity(entry.entity_id, categories={"automation": "two"})
    third = await tools.ha_config_get_automation(entity_id="uid")
    assert first["config"]["alias"] == "Before"
    assert second["config"]["alias"] == "After"
    assert first["config_hash"] != second["config_hash"]
    assert second["config_hash"] == third["config_hash"]
    assert third["config"]["category"] == "two"
    assert third["config"]["actions"] == [{"delay": 1}]
    assert "action" not in third["config"]


async def test_native_config_refuses_a_route_owned_by_another_view(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config_view(hass, "automation"), "name", "a different integration"
    )
    with pytest.raises(UnsupportedOperation):
        await backend.execute(
            "config.automation.read",
            {"identifier": "uid"},
            CallContext(hass_admin_user.id),
        )


async def test_native_script_returns_the_canonical_key_of_a_renamed_entity(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    _persist(
        hass,
        "scripts.yaml",
        {"original_key": {"alias": "Renamed", "sequence": [{"delay": 2}]}},
    )
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "script", "script", "original_key", suggested_object_id="renamed"
    )
    registry.async_update_entity(entry.entity_id, categories={"script": "one"})
    result = await ScriptReadTools(
        backend, CallContext(hass_admin_user.id)
    ).ha_config_get_script(script_id=entry.entity_id)
    assert result["script_id"] == "original_key"
    assert result["config"]["sequence"] == [{"delay": 2}]
    assert result["config"]["category"] == "one"


async def test_native_scene_discovery_finds_body_values_without_exposing_vendor_config(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
) -> None:
    _persist(
        hass,
        "scenes.yaml",
        [
            {
                "id": "saved",
                "name": "Movie",
                "entities": {"light.desk": {"effect": "Northern Lights"}},
            }
        ],
    )
    registry = er.async_get(hass)
    saved = registry.async_get_or_create(
        "scene", "homeassistant", "saved", suggested_object_id="renamed"
    )
    vendor = registry.async_get_or_create(
        "scene", "hue", "vendor", suggested_object_id="hue"
    )
    hass.states.async_set(saved.entity_id, "unknown", {"friendly_name": "Movie"})
    hass.states.async_set(vendor.entity_id, "unknown", {"friendly_name": "Hue Relax"})
    result = await SceneReadTools(
        backend, CallContext(hass_admin_user.id)
    ).ha_config_get_scene(query="northern lights", search_in_config=True)
    assert [row["scene_id"] for row in result["scenes"]] == ["saved"]
    assert result["scenes"][0]["match_in_config"] is True
    assert "config" not in result["scenes"][0]
