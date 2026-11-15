"""Compatibility fixtures still used by unconverted Native tests.

The obsolete simulated command cases are replaced by Main real-Core coverage.
Existing fixture APIs remain until their consumers use Core; no new stand-in
objects or guard exemptions are introduced here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import orjson
import pytest
import voluptuous as vol
from homeassistant.core import Context, State
from homeassistant.exceptions import HomeAssistantError

from ha_mcp.tools.search.entities import _match_exact_search_entity
from ha_mcp.utils.fuzzy_search import calculate_ratio

from ._component_ws_api import COMPONENT_VERSION, NATIVE_COMMANDS, wsapi
from ._component_ws_fakes import (
    FakeRegEntry,
    FakeServices,
    _FakeConnection,
    _FakeWSApi,
    _Unauthorized,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def FakeState(
    entity_id: str,
    state: str = "on",
    friendly_name: str | None = None,
    last_changed: str = "2026-07-16T00:00:00+00:00",
    last_updated: str = "2026-07-16T00:00:00+00:00",
    **attrs: Any,
) -> State:
    """Build Core's actual State for the existing callers of this fixture."""
    if friendly_name is not None:
        attrs["friendly_name"] = friendly_name
    return State(
        entity_id,
        state,
        attrs,
        last_changed=datetime.fromisoformat(last_changed),
        last_updated=datetime.fromisoformat(last_updated),
        context=Context(id="01ABC"),
    )


class FakeStates:
    def __init__(self, states):
        self._states = list(states)
        self._by_id = {getattr(s, "entity_id", None): s for s in self._states}

    def async_all(self):
        return list(self._states)

    def get(self, entity_id):
        return self._by_id.get(entity_id)


class FakeConfigEntries:
    def __init__(self, entries):
        self._entries = list(entries)

    def async_entries(self):
        return list(self._entries)

    def async_get_entry(self, entry_id):
        for entry in self._entries:
            if getattr(entry, "entry_id", None) == entry_id:
                return entry
        return None


class FakeHass:
    def __init__(
        self, states=(), data=None, config_entries=(), services=None, config=None
    ):
        self.states = FakeStates(states)
        self.data = dict(data or {})
        self.config_entries = FakeConfigEntries(config_entries)
        if services is not None:
            self.services = services
        if config is not None:
            self.config = config

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeEntityReg:
    def __init__(self, entries):
        self._entries = dict(entries)
        self.entities = dict(entries)

    def async_get(self, entity_id):
        return self._entries.get(entity_id)

    def async_get_entity_id(
        self, domain: str, platform: str, unique_id: str
    ) -> str | None:
        return next(
            (
                e.entity_id
                for e in self._entries.values()
                if e.platform == platform and e.unique_id == unique_id
            ),
            None,
        )


class FakeErModule:
    """Faithful stand-in for the ``entity_registry`` module's device index.

    ``_do_device_get(include_entities)`` calls ``er.async_entries_for_device``;
    a fake registry view has no real index, so tests on one monkeypatch
    ``wsapi.er`` with this. Mirrors core's filter — disabled entities are excluded
    unless ``include_disabled_entities`` (the component passes True, matching
    ``config/entity_registry/list``)."""

    @staticmethod
    def async_entries_for_device(registry, device_id, include_disabled_entities=False):
        out = []
        for entry in registry.entities.values():
            if getattr(entry, "device_id", None) != device_id:
                continue
            if not include_disabled_entities and getattr(entry, "disabled_by", None):
                continue
            out.append(entry)
        return out


class FakeArea:
    def __init__(
        self,
        area_id,
        name,
        floor_id=None,
        *,
        aliases=(),
        icon=None,
        picture=None,
        labels=(),
        humidity_entity_id=None,
        temperature_entity_id=None,
        created_at=None,
        modified_at=None,
    ):
        self.id = area_id
        self.name = name
        self.floor_id = floor_id
        self.aliases = set(aliases)
        self.icon = icon
        self.picture = picture
        self.labels = set(labels)
        self.humidity_entity_id = humidity_entity_id
        self.temperature_entity_id = temperature_entity_id
        self.created_at = created_at
        self.modified_at = modified_at


class FakeAreaReg:
    def __init__(self, areas):
        self._areas = {a.id: a for a in areas}

    def async_get_area(self, area_id):
        return self._areas.get(area_id)

    def async_list_areas(self):
        return list(self._areas.values())


class FakeFloor:
    def __init__(
        self,
        floor_id,
        name,
        *,
        level=None,
        icon=None,
        aliases=(),
        created_at=None,
        modified_at=None,
    ):
        self.floor_id = floor_id
        self.name = name
        self.level = level
        self.icon = icon
        self.aliases = set(aliases)
        self.created_at = created_at
        self.modified_at = modified_at


class FakeFloorReg:
    def __init__(self, floors):
        self._floors = {f.floor_id: f for f in floors}

    def async_get_floor(self, floor_id):
        return self._floors.get(floor_id)

    def async_list_floors(self):
        return list(self._floors.values())


class FakeLabel:
    def __init__(
        self,
        label_id,
        name,
        *,
        color=None,
        description=None,
        icon=None,
        created_at=None,
        modified_at=None,
    ):
        self.label_id = label_id
        self.name = name
        self.color = color
        self.description = description
        self.icon = icon
        self.created_at = created_at
        self.modified_at = modified_at


class FakeLabelReg:
    def __init__(self, labels):
        self._labels = {label.label_id: label for label in labels}

    def async_get_label(self, label_id):
        return self._labels.get(label_id)

    def async_list_labels(self):
        return list(self._labels.values())


class FakeCategory:
    """Stand-in for a ``CategoryEntry`` (``registries`` category rows)."""

    def __init__(
        self, category_id, name, *, icon=None, created_at=None, modified_at=None
    ):
        self.category_id = category_id
        self.name = name
        self.icon = icon
        self.created_at = created_at
        self.modified_at = modified_at


class FakeCategoryReg:
    """Stand-in for the category registry: ``async_list_categories(*, scope)``."""

    def __init__(self, by_scope):
        self._by_scope = {scope: list(cats) for scope, cats in dict(by_scope).items()}

    def async_list_categories(self, *, scope):
        return list(self._by_scope.get(scope, []))


class FakeDevice:
    def __init__(
        self,
        device_id,
        name=None,
        name_by_user=None,
        area_id=None,
        labels=(),
        manufacturer=None,
        model=None,
        identifiers=(),
        connections=(),
        config_entries=(),
        disabled_by=None,
        sw_version=None,
        hw_version=None,
        serial_number=None,
        via_device_id=None,
        model_id=None,
        configuration_url=None,
        entry_type=None,
        primary_config_entry=None,
    ):
        self.id = device_id
        self.name = name
        self.name_by_user = name_by_user
        self.area_id = area_id
        self.labels = set(labels)
        self.manufacturer = manufacturer
        self.model = model
        self.identifiers = set(identifiers)
        self.connections = set(connections)
        self.config_entries = set(config_entries)
        self.disabled_by = disabled_by
        self.sw_version = sw_version
        self.hw_version = hw_version
        self.serial_number = serial_number
        self.via_device_id = via_device_id
        self.model_id = model_id
        self.configuration_url = configuration_url
        self.entry_type = entry_type
        self.primary_config_entry = primary_config_entry

    @property
    def dict_repr(self):
        return {
            "area_id": self.area_id,
            "configuration_url": self.configuration_url,
            "config_entries": list(self.config_entries),
            "config_entries_subentries": {},
            "connections": list(self.connections),
            "created_at": 0.0,
            "disabled_by": self.disabled_by,
            "entry_type": self.entry_type,
            "hw_version": self.hw_version,
            "id": self.id,
            "identifiers": list(self.identifiers),
            "labels": list(self.labels),
            "manufacturer": self.manufacturer,
            "model": self.model,
            "model_id": self.model_id,
            "modified_at": 0.0,
            "name_by_user": self.name_by_user,
            "name": self.name,
            "primary_config_entry": self.primary_config_entry,
            "serial_number": self.serial_number,
            "sw_version": self.sw_version,
            "via_device_id": self.via_device_id,
        }


class FakeChildDevice:
    """Core 2026.9 ``ChildDeviceEntry`` with its deliberately reduced shape."""

    def __init__(
        self,
        device_id,
        parent_device_id,
        *,
        name=None,
        name_by_user=None,
        area_id=None,
        labels=(),
        identifiers=(),
        config_entry_id="cfg-1",
        config_subentry_id=None,
        disabled_by=None,
    ):
        self.id = device_id
        self.parent_device_id = parent_device_id
        self.name = name
        self.name_by_user = name_by_user
        self.area_id = area_id
        self.labels = set(labels)
        self.identifiers = set(identifiers)
        self.config_entry_id = config_entry_id
        self.config_subentry_id = config_subentry_id
        self.disabled_by = disabled_by

    def __getattr__(self, name):
        raise AttributeError(name)

    @property
    def manufacturer(self):
        pytest.fail(
            "Core 2026.9 ChildDeviceEntry does not expose manufacturer as an attribute"
        )

    @property
    def model(self):
        pytest.fail(
            "Core 2026.9 ChildDeviceEntry does not expose model as an attribute"
        )

    @property
    def connections(self):
        pytest.fail(
            "Core 2026.9 ChildDeviceEntry does not expose connections as an attribute"
        )

    @property
    def dict_repr(self):
        return {
            "area_id": self.area_id,
            "config_entry_id": self.config_entry_id,
            "config_subentry_id": self.config_subentry_id,
            "created_at": 0.0,
            "disabled_by": self.disabled_by,
            "id": self.id,
            "identifiers": list(self.identifiers),
            "labels": list(self.labels),
            "modified_at": 0.0,
            "name_by_user": self.name_by_user,
            "name": self.name,
            "parent_device_id": self.parent_device_id,
        }


class _IterOnlyDeviceCollection:
    """Core 2026.9 collection: iteration is the only supported read API."""

    def __init__(self, entries):
        self._entries = tuple(entries)

    def __iter__(self):
        return iter(self._entries)

    def values(self):
        raise AssertionError("Core 2026.9 device collections are not mappings")

    def get(self, _device_id):
        raise AssertionError("Core 2026.9 device collections do not support get")

    def __getitem__(self, _device_id):
        raise KeyError("Core 2026.9 device collections are not subscriptable")


class FakeDeviceReg:
    def __init__(self, devices, child_devices=()):
        self._devices = {d.id: d for d in devices}
        self._child_devices = {d.id: d for d in child_devices}
        self.devices = _IterOnlyDeviceCollection(self._devices.values())
        self.child_devices = _IterOnlyDeviceCollection(self._child_devices.values())

    def async_get(self, device_id):
        return self._devices.get(device_id) or self._child_devices.get(device_id)


class FakeConfigEntity:
    """Stand-in for an AutomationEntity / ScriptEntity (raw_config-bearing)."""

    def __init__(self, entity_id, name=None, unique_id=None, raw_config=None):
        self.entity_id = entity_id
        self.name = name
        self.unique_id = unique_id
        self.raw_config = raw_config


class FakeSceneEntity:
    """Stand-in for HomeAssistantScene (scene_config, not raw_config)."""

    def __init__(self, entity_id, name=None, unique_id=None, scene_config=None):
        self.entity_id = entity_id
        self.name = name
        self.unique_id = unique_id
        self.scene_config = scene_config


class FakeCollectionEntity:
    """Stand-in for an entity that keeps the config it was built from as ``_config``
    (a zone, including the home zone built from the core configuration), reachable
    via the domain's EntityComponent in ``hass.data['entity_components']``.
    """

    def __init__(self, entity_id, config, unique_id=None):
        self.entity_id = entity_id
        self._config = dict(config)
        self.unique_id = unique_id if unique_id is not None else config.get("id")


class FakeComponent:
    def __init__(self, entities):
        self.entities = list(entities)


class FakeStorageCollection:
    """Core's ``StorageCollection``: ``async_items()`` is what ``<type>/list`` sends."""

    def __init__(self, items: Iterable[Mapping[str, Any]]) -> None:
        self._items = [dict(item) for item in items]

    def async_items(self) -> list[dict[str, Any]]:
        return list(self._items)


class FakeStorageCollectionWs:
    """Core's ``StorageCollectionWebsocket``, reached through ``<type>/create``."""

    def __init__(self, items: Iterable[Mapping[str, Any]]) -> None:
        self.storage_collection = FakeStorageCollection(items)
        self.create_schema = {}
        self.update_schema = {}

    async def ws_create_item(  # pragma: no cover
        self, hass: Any, connection: Any, msg: dict[str, Any]
    ) -> None:
        raise AssertionError("never invoked")


def stored_helpers(
    collections: Mapping[str, Iterable[Mapping[str, Any]]],
) -> dict[str, Any]:
    """``hass.data`` holding Core's WS handlers for ``{type: [stored items]}``."""
    return {
        "websocket_api": {
            f"{helper_type}/create": (FakeStorageCollectionWs(items).ws_create_item, {})
            for helper_type, items in collections.items()
        }
    }


class FakeConfigEntry:
    def __init__(
        self,
        domain,
        title="",
        options=None,
        data=None,
        entry_id="entry",
        *,
        unique_id=None,
        state=None,
        source="user",
        supports_options=False,
        supports_remove_device=None,
        supports_unload=None,
        supports_reconfigure=False,
        pref_disable_new_entities=False,
        pref_disable_polling=False,
        disabled_by=None,
        reason=None,
        error_reason_translation_domain=None,
        error_reason_translation_key=None,
        error_reason_translation_placeholders=None,
        subentries=None,
        created_at=None,
        modified_at=None,
        supported_subentry_types=None,
    ):
        self.domain = domain
        self.title = title
        self.options = dict(options or {})
        self.data = dict(data or {})
        self.entry_id = entry_id
        self.unique_id = unique_id
        self.state = state
        self.source = source
        self.supports_options = supports_options
        self.supports_remove_device = supports_remove_device
        self.supports_unload = supports_unload
        self.supports_reconfigure = supports_reconfigure
        self.pref_disable_new_entities = pref_disable_new_entities
        self.pref_disable_polling = pref_disable_polling
        self.disabled_by = disabled_by
        self.reason = reason
        self.error_reason_translation_domain = error_reason_translation_domain
        self.error_reason_translation_key = error_reason_translation_key
        self.error_reason_translation_placeholders = (
            error_reason_translation_placeholders
        )
        self.subentries = dict(subentries or {})
        self.created_at = created_at
        self.modified_at = modified_at
        self.supported_subentry_types = supported_subentry_types or {}
        self.extra_fragment_fields: dict[str, Any] = {}

    @property
    def as_json_fragment(self):
        """Stand-in for Core's ``ConfigEntry.as_json_fragment``.

        Unlike Core it tolerates ``None`` timestamps and subentries, so
        flow-helper fixtures that omit them still build a row.
        """

        def _ts(value):
            return value.timestamp() if value is not None else None

        def _val(value):
            return getattr(value, "value", value)

        row = {
            "created_at": _ts(self.created_at),
            "entry_id": self.entry_id,
            "domain": self.domain,
            "modified_at": _ts(self.modified_at),
            "title": self.title,
            "source": self.source,
            "state": _val(self.state),
            "supports_options": self.supports_options,
            "supports_remove_device": self.supports_remove_device or False,
            "supports_unload": self.supports_unload or False,
            "supports_reconfigure": self.supports_reconfigure,
            "supported_subentry_types": self.supported_subentry_types,
            "pref_disable_new_entities": self.pref_disable_new_entities,
            "pref_disable_polling": self.pref_disable_polling,
            "disabled_by": _val(self.disabled_by),
            "reason": self.reason,
            "error_reason_translation_domain": self.error_reason_translation_domain,
            "error_reason_translation_key": self.error_reason_translation_key,
            "error_reason_translation_placeholders": (
                self.error_reason_translation_placeholders
            ),
            "num_subentries": len(self.subentries or {}),
            **self.extra_fragment_fields,
        }
        return orjson.Fragment(json.dumps(row).encode())


class FakeSubentry:
    """Stand-in for a ``ConfigSubentry`` (config_entries row's subentries)."""

    def __init__(self, subentry_id, subentry_type, title, unique_id=None, data=None):
        self.subentry_id = subentry_id
        self.subentry_type = subentry_type
        self.title = title
        self.unique_id = unique_id
        self.data = dict(data or {})


class FakeConfig:
    """Stand-in for ``hass.config``: ``path()`` roots at a temp dir; ``as_dict()``
    returns the injected HA-config payload (overview's system-info slice);
    ``time_zone`` is the attribute ``_do_info`` reads for the additive timezone
    field."""

    def __init__(self, base_dir=None, data=None, time_zone=None):
        self._base = Path(base_dir) if base_dir is not None else None
        self._data = dict(data or {})
        self.time_zone = time_zone

    def path(self, *parts):
        return str(self._base.joinpath(*parts))

    def as_dict(self):
        return dict(self._data)


class FakeIssue:
    """Stand-in for an issue-registry ``IssueEntry`` (repairs slice)."""

    def __init__(
        self,
        issue_id,
        domain,
        *,
        severity="warning",
        translation_key=None,
        dismissed_version=None,
        is_fixable=True,
        breaks_in_ha_version=None,
        created=None,
        issue_domain=None,
        translation_placeholders=None,
        learn_more_url=None,
        active=True,
    ):
        self.issue_id = issue_id
        self.domain = domain
        self.severity = severity
        self.translation_key = translation_key
        self.dismissed_version = dismissed_version
        self.is_fixable = is_fixable
        self.breaks_in_ha_version = breaks_in_ha_version
        self.created = created
        self.issue_domain = issue_domain
        self.translation_placeholders = translation_placeholders
        self.learn_more_url = learn_more_url
        self.active = active


class FakeIssueRegistry:
    """Stand-in for the issue registry: ``.issues`` maps (domain, id) -> IssueEntry."""

    def __init__(self, issues):
        self.issues = {(i.domain, i.issue_id): i for i in issues}


class FakeIssueRegModule:
    """Stand-in for the ``issue_registry`` module (``async_get`` seam)."""

    def __init__(self, registry):
        self._registry = registry

    def async_get(self, hass):
        return self._registry


def make_view(
    entity=None, areas=(), floors=(), labels=(), devices=(), child_devices=()
):
    return wsapi._RegistryView(
        entity=FakeEntityReg(entity or {}),
        area=FakeAreaReg(areas),
        floor=FakeFloorReg(floors),
        label=FakeLabelReg(labels),
        device=FakeDeviceReg(devices, child_devices),
    )


@pytest.fixture
def empty_view(monkeypatch):
    """Patch _resolve_registries to an all-None view (states-only join)."""
    monkeypatch.setattr(
        wsapi, "_resolve_registries", lambda hass: wsapi._RegistryView()
    )


_PARITY_CORPUS = [
    ("light.kitchen", "Kitchen Light"),
    ("light.kitchen_ceiling", "Kitchen Ceiling"),
    ("switch.kitchen", "Kitchen Switch"),
    ("sensor.temperature", "Temperature"),
    ("light.bedroom", "Bedroom Light"),
]
_PARITY_HIDDEN = {"light.bedroom"}
_PARITY_QUERIES = [
    "kitchen",
    "light.kitchen",
    "temperature",
    "bedroom",
    "kitchen light",
]


@pytest.fixture
def functional_ws(monkeypatch):
    fake = _FakeWSApi()
    monkeypatch.setattr(wsapi, "websocket_api", fake)
    monkeypatch.setattr(
        wsapi, "_resolve_registries", lambda hass: wsapi._RegistryView()
    )
    wsapi.async_register_commands(FakeHass())
    return fake


_ALL_COMMANDS = [
    "ha_mcp_tools/info",
    "ha_mcp_tools/search",
    "ha_mcp_tools/overview",
    "ha_mcp_tools/helpers_list",
    "ha_mcp_tools/states",
    "ha_mcp_tools/blueprint_get",
    "ha_mcp_tools/device_get",
    "ha_mcp_tools/device_list",
    "ha_mcp_tools/entity_enrich",
    "ha_mcp_tools/exposure",
    "ha_mcp_tools/config_entries",
    "ha_mcp_tools/registry_lookup",
    "ha_mcp_tools/system_snapshot",
    "ha_mcp_tools/entity_lookup",
    "ha_mcp_tools/registries",
    "ha_mcp_tools/call_event",
]

_CMD_MSG_EXTRA: dict[str, dict[str, object]] = {
    "ha_mcp_tools/states": {"entity_ids": []},
    "ha_mcp_tools/blueprint_get": {"domain": "automation", "path": "x.yaml"},
    "ha_mcp_tools/device_get": {"device_id": "d1"},
    "ha_mcp_tools/entity_enrich": {"entity_ids": []},
    "ha_mcp_tools/entity_lookup": {"unique_id": "x"},
    "ha_mcp_tools/registries": {"registries": []},
    "ha_mcp_tools/registry_lookup": {"entity_ids": ["light.x"]},
    "ha_mcp_tools/call_event": {"event_type": "probe_event"},
}


def _zha_device():
    """A DeviceEntry-ish fake carrying the fields the server transforms read."""
    return FakeDevice(
        "dev-1",
        name="Kitchen Sensor",
        name_by_user="Kitchen",
        area_id="a1",
        labels=("important",),
        manufacturer="Aqara",
        model="T1",
        identifiers=(("zha", "00:11:22:33:44:55:66:77"),),
        connections=(("zigbee", "00:11:22:33:44:55:66:77"),),
        config_entries=("cfg-1",),
        disabled_by=None,
        sw_version="1.2.3",
        via_device_id="coordinator-1",
    )


_REG_CREATED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
_REG_MODIFIED = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)


__all__ = [
    "Any",
    "COMPONENT_VERSION",
    "Context",
    "FakeArea",
    "FakeAreaReg",
    "FakeCategory",
    "FakeCategoryReg",
    "FakeChildDevice",
    "FakeCollectionEntity",
    "FakeComponent",
    "FakeConfig",
    "FakeConfigEntity",
    "FakeConfigEntries",
    "FakeConfigEntry",
    "FakeDevice",
    "FakeDeviceReg",
    "FakeEntityReg",
    "FakeErModule",
    "FakeFloor",
    "FakeFloorReg",
    "FakeHass",
    "FakeIssue",
    "FakeIssueRegModule",
    "FakeIssueRegistry",
    "FakeLabel",
    "FakeLabelReg",
    "FakeRegEntry",
    "FakeSceneEntity",
    "FakeServices",
    "FakeState",
    "FakeStates",
    "FakeStorageCollection",
    "FakeStorageCollectionWs",
    "FakeSubentry",
    "HomeAssistantError",
    "Iterable",
    "Mapping",
    "NATIVE_COMMANDS",
    "Path",
    "SimpleNamespace",
    "State",
    "UTC",
    "_ALL_COMMANDS",
    "_FakeConnection",
    "_FakeWSApi",
    "_IterOnlyDeviceCollection",
    "_PARITY_CORPUS",
    "_PARITY_HIDDEN",
    "_PARITY_QUERIES",
    "_REG_CREATED",
    "_REG_MODIFIED",
    "_REPO_ROOT",
    "_Unauthorized",
    "_match_exact_search_entity",
    "_zha_device",
    "asyncio",
    "calculate_ratio",
    "datetime",
    "empty_view",
    "functional_ws",
    "json",
    "logging",
    "make_view",
    "orjson",
    "pytest",
    "stored_helpers",
    "vol",
    "wsapi",
]
