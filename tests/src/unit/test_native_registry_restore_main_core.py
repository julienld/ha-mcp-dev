"""Native restores retain Main's recreation behavior on actual Core registries."""

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import category_registry as cr
from homeassistant.helpers import label_registry as lr
from homeassistant.setup import async_setup_component

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_operations.labels import NativeLabels
from ha_mcp.runtime.snapshot_registry_restore import current_registry, restore_registry
from ha_mcp.tool_api import CallContext

from ._native_core_backend import backend as backend


async def test_native_label_partial_update_clear_and_actual_core_related_set(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    registry = lr.async_get(hass)
    label = registry.async_create("Security", color="red", icon="mdi:star")
    area = ar.async_get(hass).async_create("Office", labels={label.label_id})
    service = NativeLabels(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    )
    await service.set(label_id=label.label_id, color=" ", description=" details ")
    stored = registry.async_get_label(label.label_id)
    assert stored is not None
    assert (stored.name, stored.color, stored.icon, stored.description) == (
        "Security",
        None,
        "mdi:star",
        "details",
    )
    result = await service.get(label.label_id)
    assert area.id in result["related"]["area"]


@pytest.fixture(autouse=True)
async def config_commands(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "config", {})


async def test_removed_renamed_label_is_recreated_with_its_core_id_disclosed(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    registry = lr.async_get(hass)
    label = registry.async_create("Original", color="red")
    registry.async_update(label.label_id, name="Renamed")
    service = NativeLabels(
        hass, CallContext(hass_admin_user.id), authorize=backend.authorize
    )
    snapshot = await service.read_snapshot(label.label_id)
    assert snapshot is not None
    registry.async_delete(label.label_id)

    result = await service.restore_snapshot(label.label_id, snapshot, None)

    restored = registry.async_get_label(result["label_id"])
    assert restored is not None
    assert (restored.name, restored.color) == ("Renamed", "red")
    assert restored.label_id != label.label_id
    assert any(label.label_id in warning for warning in result["warnings"])
    repeated = await service.restore_snapshot(label.label_id, snapshot, None)
    assert repeated["label_id"] == restored.label_id
    assert len(list(registry.async_list_labels())) == 1


async def test_deleted_category_restores_once_without_reusing_its_old_identity(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    registry = cr.async_get(hass)
    category = registry.async_create(
        scope="automation", name="Important", icon="mdi:star"
    )
    actor = CallContext(hass_admin_user.id)
    identifier = f"automation:{category.category_id}"
    snapshot = await current_registry(
        backend,
        actor,
        "category",
        identifier,
        {"scope": "automation", "category_id": category.category_id},
    )
    assert snapshot is not None
    registry.async_delete(scope="automation", category_id=category.category_id)

    result = await restore_registry(
        backend, actor, "category", identifier, snapshot, None
    )

    restored = registry.async_get_category(
        scope="automation", category_id=result["category_id"]
    )
    assert restored is not None
    assert (restored.name, restored.icon) == ("Important", "mdi:star")
    assert restored.category_id != category.category_id
    repeated = await restore_registry(
        backend, actor, "category", identifier, snapshot, None
    )
    assert repeated["category_id"] == restored.category_id
    assert len(list(registry.async_list_categories(scope="automation"))) == 1
