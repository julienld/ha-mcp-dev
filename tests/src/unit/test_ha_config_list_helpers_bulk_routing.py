"""Bulk helper listing preserves coverage, fallback and error contracts."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.rest_client import (
    HomeAssistantCommandError,
    HomeAssistantConnectionError,
)
from ha_mcp.runtime import helper_flows as flow_catalog
from ha_mcp.tools import helper_flows, tools_config_helpers
from ha_mcp.tools.config_helpers.schemas import SIMPLE_HELPER_TYPES

from ._component_routing_helpers import make_ws, patch_ws
from ._core_helper_flows import CORE_HELPER_FLOWS
from .test_ha_config_list_helpers_component_routing import (
    _CAPS_HELPERS,
    RoutingClient,
    _build_list_helpers,
    _helpers_calls,
)
from .test_ha_config_list_helpers_component_routing import (
    _clear_caps_cache as _clear_caps_cache,
)

# --- all-types (helper_type="all") bulk mode -------------------------------------


def _component_all_result() -> dict[str, Any]:
    """Merged component output: one collection helper + one flow helper.

    ``covered_types`` mirrors the real component: every simple type EXCEPT
    ``person`` and ``tag`` (whose ``<type>/list`` adds more than the stored
    items) plus the FULL flow universe (``covered |= FLOW_HELPER_DOMAINS``
    component-side — not just types with instances). So only those two fall
    back to the legacy per-type list, and no flow type triggers the
    incomplete-coverage hard error.
    """
    return {
        "helpers": [
            {
                "helper_type": "input_boolean",
                "object_id": "abc123",
                "entity_id": "input_boolean.foo",
                "name": "New Name",
                "kind": "collection",
                "storage_id": "abc123",
                "config": {"id": "abc123", "name": "Old Name", "icon": "mdi:flash"},
            },
            {
                "helper_type": "template",
                "entry_id": "cfgentry123",
                "entity_id": "sensor.templated",
                "name": "Templated Sensor",
                "kind": "flow",
                "options": {"state": "{{ 1 + 1 }}"},
            },
        ],
        "count": 2,
        "covered_types": sorted(
            (SIMPLE_HELPER_TYPES - {"person", "tag"}) | CORE_HELPER_FLOWS
        ),
    }


@pytest.mark.asyncio
async def test_all_types_via_component_returns_merged_listing() -> None:
    """helper_type='all' merges component records + legacy person/tag lists."""
    ws = make_ws(
        "ha_mcp_tools/helpers_list",
        info_result=_CAPS_HELPERS,
        cmd_result=_component_all_result(),
    )
    client = RoutingClient()
    list_helpers = _build_list_helpers(client)

    with patch_ws(ws, tools_config_helpers):
        resp = await list_helpers(helper_type="all")

    assert resp["success"] is True
    assert resp["helper_type"] == "all"
    # Collection + flow (component) + person x2 + tag (legacy fallbacks).
    assert resp["count"] == 5
    by_type = {h.get("helper_type"): h for h in resp["helpers"]}
    assert set(by_type) == {"input_boolean", "template", "person", "tag"}
    # Collection record: #1794 shape preserved and self-describes its type.
    assert by_type["input_boolean"]["id"] == "abc123"
    assert by_type["input_boolean"]["entity_id"] == "input_boolean.foo"
    assert by_type["input_boolean"]["name"] == "New Name"
    # Flow record: entry_id + options carried through.
    assert by_type["template"]["entry_id"] == "cfgentry123"
    assert by_type["template"]["options"] == {"state": "{{ 1 + 1 }}"}
    # Person and tag came from the legacy fallback (the uncovered simple types).
    assert by_type["tag"]["id"] == "tag-42"
    assert client.list_calls == 2
    # The component command requests all types (no helper_types filter).
    (call,) = _helpers_calls(ws)
    assert "helper_types" not in call.kwargs
    assert call.kwargs["include_flow_helpers"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("helper_type", ["input_boolean", "all"])
async def test_yaml_helper_is_not_listed_as_a_stored_helper(helper_type: str) -> None:
    """input_boolean/list lists stored helpers only. A YAML-defined one, which
    the component sends with a null storage id and its state attributes, must
    not appear as though those attributes were its stored config."""
    result = _component_all_result()
    result["helpers"].append(
        {
            "helper_type": "input_boolean",
            "object_id": "yaml_flag",
            "entity_id": "input_boolean.yaml_flag",
            "name": "YAML Flag",
            "kind": "collection",
            "storage_id": None,
            "config": {"friendly_name": "YAML Flag", "editable": False},
        }
    )
    ws = make_ws(
        "ha_mcp_tools/helpers_list", info_result=_CAPS_HELPERS, cmd_result=result
    )
    list_helpers = _build_list_helpers(RoutingClient())

    with patch_ws(ws, tools_config_helpers):
        resp = await list_helpers(helper_type=helper_type)

    listed = {h.get("entity_id") for h in resp["helpers"]}
    assert "input_boolean.foo" in listed
    assert "input_boolean.yaml_flag" not in listed


@pytest.mark.asyncio
async def test_all_types_refuses_a_listing_that_misses_a_custom_helper_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A helper flow Core lists but the component did not cover (an older
    component without custom helpers) -> hard error, not a partial listing."""
    monkeypatch.setattr(
        flow_catalog,
        "_fetch_helper_flow_types",
        AsyncMock(return_value=CORE_HELPER_FLOWS | {"my_custom_helper"}),
    )
    ws = make_ws(
        "ha_mcp_tools/helpers_list",
        info_result=_CAPS_HELPERS,
        cmd_result=_component_all_result(),
    )
    list_helpers = _build_list_helpers(RoutingClient())

    with patch_ws(ws, tools_config_helpers), pytest.raises(ToolError) as excinfo:
        await list_helpers(helper_type="all")

    assert json.loads(str(excinfo.value))["error"]["code"] == "COMPONENT_NOT_INSTALLED"
    assert "my_custom_helper" in str(excinfo.value)


@pytest.mark.asyncio
async def test_all_types_reads_the_helper_flows_afresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A helper integration uninstalled since the cached read is not reported
    as missing from the component's listing."""
    monkeypatch.setattr(
        flow_catalog,
        "_fetch_helper_flow_types",
        AsyncMock(side_effect=[CORE_HELPER_FLOWS | {"gone_helper"}, CORE_HELPER_FLOWS]),
    )
    client = RoutingClient()
    await helper_flows.helper_flow_types(client)
    ws = make_ws(
        "ha_mcp_tools/helpers_list",
        info_result=_CAPS_HELPERS,
        cmd_result=_component_all_result(),
    )
    with patch_ws(ws, tools_config_helpers):
        resp = await _build_list_helpers(client)(helper_type="all")
    assert resp["success"] is True


@pytest.mark.asyncio
async def test_all_types_with_an_unreadable_helper_flow_list_is_a_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fresh helper-flow read that checks the component's coverage fails:
    a structured connection error, not a raw exception or a partial listing."""
    monkeypatch.setattr(
        flow_catalog,
        "_fetch_helper_flow_types",
        AsyncMock(side_effect=HomeAssistantConnectionError("flow_handlers down")),
    )
    ws = make_ws(
        "ha_mcp_tools/helpers_list",
        info_result=_CAPS_HELPERS,
        cmd_result=_component_all_result(),
    )
    client = RoutingClient()
    list_helpers = _build_list_helpers(client)

    with patch_ws(ws, tools_config_helpers), pytest.raises(ToolError) as excinfo:
        await list_helpers(helper_type="all")

    payload = json.loads(str(excinfo.value))
    assert payload["error"]["code"] == "CONNECTION_FAILED"
    assert payload["helper_type"] == "all"
    assert client.list_calls == 0


@pytest.mark.asyncio
async def test_a_custom_helper_flow_left_out_by_a_failed_loader_read_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An installed component whose loader read failed is not told to update."""
    monkeypatch.setattr(
        flow_catalog,
        "_fetch_helper_flow_types",
        AsyncMock(return_value=CORE_HELPER_FLOWS | {"my_custom_helper"}),
    )
    result = _component_all_result() | {"helper_flows_degraded": True}
    ws = make_ws(
        "ha_mcp_tools/helpers_list", info_result=_CAPS_HELPERS, cmd_result=result
    )
    list_helpers = _build_list_helpers(RoutingClient())

    with patch_ws(ws, tools_config_helpers), pytest.raises(ToolError) as excinfo:
        await list_helpers(helper_type="my_custom_helper")

    error = json.loads(str(excinfo.value))["error"]
    assert error["code"] == "SERVICE_CALL_FAILED"
    assert "loader" in error["message"]
    assert "my_custom_helper" in error["message"]


@pytest.mark.asyncio
async def test_all_types_without_component_raises_component_required() -> None:
    """helper_type='all' with no component surface → hard COMPONENT_NOT_INSTALLED."""
    ws = make_ws(
        "ha_mcp_tools/helpers_list",
        info_exc=HomeAssistantCommandError(
            "Command failed: no info", "unknown_command"
        ),
    )
    client = RoutingClient()
    list_helpers = _build_list_helpers(client)

    with patch_ws(ws, tools_config_helpers), pytest.raises(ToolError) as excinfo:
        await list_helpers(helper_type="all")

    assert json.loads(str(excinfo.value))["error"]["code"] == "COMPONENT_NOT_INSTALLED"
    # Never falls back to any legacy list and never issues the component command.
    assert client.list_calls == 0
    assert not _helpers_calls(ws)


@pytest.mark.asyncio
async def test_all_types_component_error_raises_component_required() -> None:
    """A component handler error on helper_type='all' → same hard error, no legacy."""
    ws = make_ws(
        "ha_mcp_tools/helpers_list",
        info_result=_CAPS_HELPERS,
        cmd_exc=HomeAssistantCommandError("Command failed: boom", "internal_error"),
    )
    client = RoutingClient()
    list_helpers = _build_list_helpers(client)

    with patch_ws(ws, tools_config_helpers), pytest.raises(ToolError) as excinfo:
        await list_helpers(helper_type="all")

    assert json.loads(str(excinfo.value))["error"]["code"] == "COMPONENT_NOT_INSTALLED"
    # No legacy all-types path exists, so nothing is served from legacy.
    assert client.list_calls == 0
