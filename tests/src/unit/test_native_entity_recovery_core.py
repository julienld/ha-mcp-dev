"""Entity empty reads and missing-identity recovery keep Main's contract."""

import json
from types import SimpleNamespace

import pytest
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from custom_components.ha_mcp_tools.native_snapshot_domains import NativeSnapshotDomains
from ha_mcp.runtime.entities import EntityDiscoveryTools
from ha_mcp.runtime.snapshot_payloads import BackupRestoreError
from ha_mcp.tool_api import CallContext

from ._native_core_backend import backend as backend


async def test_empty_entity_list_has_no_unrequested_message(
    hass_admin_user: User, backend: NativeBackend
) -> None:
    result = await EntityDiscoveryTools(
        backend, CallContext(hass_admin_user.id)
    ).ha_get_entity([])
    assert result == {"success": True, "entity_entries": [], "count": 0}


async def test_native_deleted_entity_explains_core_retention_without_recreation(
    hass: HomeAssistant, hass_admin_user: User, backend: NativeBackend
) -> None:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create("sensor", "test", "deleted_native")
    saved = json.loads(json.dumps(entry.extended_dict))
    registry.async_remove(entry.entity_id)
    domains = NativeSnapshotDomains(SimpleNamespace(hass=hass, backend=backend))
    with pytest.raises(BackupRestoreError) as caught:
        await domains.restore_entity_registry(
            {"entity_id": entry.id, "config": saved},
            None,
            CallContext(hass_admin_user.id),
        )
    assert caught.value.outcome["reason"] == "entry_deleted"
    assert f"keeps the registry settings of {entry.entity_id} until " in json.dumps(
        caught.value.outcome
    )
    assert registry.async_get(entry.entity_id) is None
