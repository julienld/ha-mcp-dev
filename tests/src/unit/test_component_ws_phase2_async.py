"""Compatibility fixtures still used by unconverted Native tests.

The obsolete simulated command cases are replaced by Main real-Core coverage.
Existing fixture APIs remain until their consumers use Core; no new stand-in
objects or guard exemptions are introduced here.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
import voluptuous as vol
from homeassistant.components.lovelace.const import ConfigNotFound
from homeassistant.core import HomeAssistant, is_callback
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

from ._component_ws_fakes import _FakeBulkServices, _FakeCallServices
from .test_component_ws_search import (
    FakeChildDevice,
    FakeConfigEntry,
    FakeDevice,
    FakeHass,
    FakeRegEntry,
    FakeServices,
    FakeState,
    _FakeConnection,
    _FakeWSApi,
    _Unauthorized,
    make_view,
    wsapi,
)


class FakeDashboard:
    """Stand-in for a core ``LovelaceConfig`` (LovelaceStorage / LovelaceYAML).

    ``config`` is the stored collection item + url_path (list-mode metadata);
    ``mode`` is ``storage``/``yaml``; ``async_load(force)`` returns the body (or
    raises ``load_error`` to exercise the fail-soft paths).
    """

    def __init__(
        self, url_path, mode="storage", config=None, body=None, load_error=None
    ):
        self._url_path = url_path
        self.mode = mode
        self.config = config
        self._body = body
        self._load_error = load_error

    @property
    def url_path(self):
        return self._url_path

    async def async_load(self, force):
        if self._load_error is not None:
            raise self._load_error
        return self._body


class FakeLovelaceData:
    """Stand-in for core's ``LovelaceData`` dataclass (only ``.dashboards`` read)."""

    def __init__(self, dashboards):
        self.dashboards = dict(dashboards)


def _storage_dash(url_path, title, *, body=None, icon="mdi:home", **extra):
    config = {
        "id": f"id-{url_path}",
        "url_path": url_path,
        "title": title,
        "icon": icon,
        "show_in_sidebar": True,
        "require_admin": False,
    }
    config.update(extra)
    return FakeDashboard(url_path, "storage", config=config, body=body)


@pytest.fixture
def patch_dashboards(monkeypatch):
    """Return a setter that patches ``_lovelace_dashboards_map`` to a fixed map."""

    def _set(dashboards_map):
        monkeypatch.setattr(
            wsapi, "_lovelace_dashboards_map", lambda hass: dashboards_map
        )

    return _set


def _run_dashboards(hass: FakeHass, msg):
    extra = asyncio.run(wsapi._dashboards_prep(hass, msg))
    return wsapi._do_dashboards(hass, msg, **extra)


_DESCRIPTIONS = {
    "light": {
        "turn_on": {"name": "Turn on", "description": "Turn a light on", "fields": {}},
        "turn_off": {"name": "Turn off", "description": "Turn a light off"},
    },
    "climate": {
        "set_temperature": {
            "name": "Set temperature",
            "description": "Set the target temperature",
        }
    },
}
_TRANSLATIONS = {
    "component.light.services.turn_on.name": "Turn on",
    "component.light.services.turn_on.description": "Switch a light on",
    "component.climate.services.set_temperature.name": "Set temperature",
}


def _always_expose(_eid):
    return True


def _boom(*_a, **_k):
    raise AssertionError("must not be consulted")


_NEW_COMMANDS = [
    "ha_mcp_tools/dashboards",
    "ha_mcp_tools/services_list",
    "ha_mcp_tools/reference_data",
    "ha_mcp_tools/server_entry",
    "ha_mcp_tools/call_event",
]

_NEW_CMD_MSG_EXTRA = {
    "ha_mcp_tools/dashboards": {"mode": "list"},
    "ha_mcp_tools/call_event": {"event_type": "probe_event"},
}


@pytest.fixture
def functional_ws(monkeypatch):
    fake = _FakeWSApi()
    monkeypatch.setattr(wsapi, "websocket_api", fake)
    monkeypatch.setattr(
        wsapi, "_resolve_registries", lambda hass: wsapi._RegistryView()
    )
    monkeypatch.setattr(wsapi, "_lovelace_dashboards_map", lambda hass: None)

    async def _empty_desc(hass: HomeAssistant):
        return {}

    async def _empty_trans(hass: HomeAssistant, language):
        return {}

    monkeypatch.setattr(wsapi, "_fetch_service_descriptions", _empty_desc)
    monkeypatch.setattr(wsapi, "_fetch_service_translations", _empty_trans)
    wsapi.async_register_commands(FakeHass())
    return fake


class _FakeEvent:
    """A ``state_changed`` event — only ``.data`` is read by the listener."""

    def __init__(self, entity_id, new_state):
        self.data = {"entity_id": entity_id, "new_state": new_state}


class _FakeBus:
    """Records ``async_listen`` callbacks; lets a test fire a state_changed event.

    ``async_listen(event_type, cb)`` stores ``cb`` and returns an unsub that counts
    its calls; ``fire(entity_id, new_state)`` drives every stored callback with a
    fake event (simulating the in-process bus delivering the confirming transition).
    """

    def __init__(self):
        self.listeners = []
        self.unsub_count = 0

    def async_listen(self, event_type, cb):
        self.listeners.append((event_type, cb))

        def _unsub():
            self.unsub_count += 1

        return _unsub

    def fire(self, entity_id, new_state):
        event = _FakeEvent(entity_id, new_state)
        for _event_type, cb in list(self.listeners):
            cb(event)


def _call_hass(states, services, bus):
    hass = FakeHass(states=list(states), services=services)
    hass.bus = bus
    return hass


def _run_call_service(hass: HomeAssistant, msg):
    """Drive the async prep then the pure formatter, as the WS wrapper does."""
    extra = asyncio.run(wsapi._call_service_prep(hass, msg))
    return wsapi._do_call_service(hass, msg, **extra)


_HA_MCP_TOOLS_DOMAIN_VARIANTS = [
    "ha_mcp_tools",
    "HA_MCP_TOOLS",
    " ha_mcp_tools ",
    "ha_mcp_tools\n",
    "\tha_mcp_tools",
    "\u00a0ha_mcp_tools\u00a0",  # NBSP-padded (U+00A0)
]


class _AmbiguousBool:
    """A truth value that raises when coerced to bool — like numpy's array-bool.

    numpy itself raises ``ValueError`` ("truth value ... is ambiguous"); we raise
    ``TypeError`` (the conventional ``__bool__``-failure type) since the exact type
    is immaterial to the code under test — ``_values_differ`` catches any exception
    and falls back to a ``repr`` compare.
    """

    def __bool__(self):
        raise TypeError(
            "truth value of an array with more than one element is ambiguous"
        )


class _ArrayLike:
    """An attribute value whose ``!=`` returns a non-bool (``_AmbiguousBool``).

    Exactly the shape (numpy array / pandas value) that makes a naive
    ``old != new`` blow up inside the attribute diff. ``_values_differ`` must fall
    back to a ``repr`` compare instead of raising.
    """

    def __init__(self, values):
        self._values = list(values)

    def __eq__(self, other):
        return _AmbiguousBool()

    def __ne__(self, other):
        return _AmbiguousBool()

    __hash__ = None  # unhashable, like a list/array — never keyed on in the diff

    def __repr__(self):
        return f"_ArrayLike({self._values!r})"


def _run_bulk_call_service(hass: HomeAssistant, msg):
    """Drive the async prep then the pure formatter, as the WS wrapper does."""
    extra = asyncio.run(wsapi._bulk_call_service_prep(hass, msg))
    return wsapi._do_bulk_call_service(hass, msg, **extra)


__all__ = [
    "ConfigNotFound",
    "FakeChildDevice",
    "FakeConfigEntry",
    "FakeDashboard",
    "FakeDevice",
    "FakeHass",
    "FakeLovelaceData",
    "FakeRegEntry",
    "FakeServices",
    "FakeState",
    "HomeAssistant",
    "HomeAssistantError",
    "ServiceNotFound",
    "SimpleNamespace",
    "_AmbiguousBool",
    "_ArrayLike",
    "_DESCRIPTIONS",
    "_FakeBulkServices",
    "_FakeBus",
    "_FakeCallServices",
    "_FakeConnection",
    "_FakeEvent",
    "_FakeWSApi",
    "_HA_MCP_TOOLS_DOMAIN_VARIANTS",
    "_NEW_CMD_MSG_EXTRA",
    "_NEW_COMMANDS",
    "_TRANSLATIONS",
    "_Unauthorized",
    "_always_expose",
    "_boom",
    "_call_hass",
    "_run_bulk_call_service",
    "_run_call_service",
    "_run_dashboards",
    "_storage_dash",
    "asyncio",
    "functional_ws",
    "is_callback",
    "make_view",
    "patch_dashboards",
    "pytest",
    "sys",
    "vol",
    "wsapi",
]
