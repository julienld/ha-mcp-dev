"""Service boundaries run through Core's real WS framing and service registry."""

import copy
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.auth.models import User
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.client.rest_client import (
    HomeAssistantClient,
    HomeAssistantCommandNotSent,
)
from ha_mcp.client.websocket_client import (
    HomeAssistantWebSocketClient,
    get_websocket_client,
)
from ha_mcp.tools import component_api, tools_service
from ha_mcp.tools.tools_service import ServiceTools


@dataclass
class _Boundary:
    hass: HomeAssistant
    client: HomeAssistantClient
    socket: HomeAssistantWebSocketClient
    tools: ServiceTools
    calls: list[ServiceCall] = field(default_factory=list)
    response: ServiceResponse = None
    failure: type[Exception] | None = None
    confirm: bool = True
    drop_reply: bool = False


@pytest.fixture
async def boundary(
    hass: HomeAssistant, component_core_client: HomeAssistantClient
) -> AsyncIterator[_Boundary]:
    socket = await get_websocket_client(
        component_core_client.base_url, component_core_client.token, verify_ssl=False
    )
    state = _Boundary(
        hass, component_core_client, socket, ServiceTools(component_core_client, None)
    )
    hass.states.async_set("light.boundary", "off")

    async def turn_on(call: ServiceCall) -> ServiceResponse:
        state.calls.append(call)
        if state.confirm:
            hass.states.async_set("light.boundary", "on", context=call.context)
        if state.drop_reply:
            await state.socket.disconnect()
        if state.failure is not None:
            raise state.failure(
                "403 Forbidden: handler failed after changing the device"
            )
        return copy.deepcopy(state.response)

    hass.services.async_register(
        "light", "turn_on", turn_on, supports_response=SupportsResponse.OPTIONAL
    )
    assert await component_api.get_component_caps(component_core_client) is not None
    yield state
    await hass.async_block_till_done()


@pytest.mark.parametrize("failure", [HomeAssistantError, RuntimeError])
async def test_mutation_then_command_error_is_unknown_without_rest_replay(
    boundary: _Boundary, hass_admin_user: User, failure: type[Exception]
) -> None:
    boundary.failure = failure
    with (
        patch.object(
            boundary.client, "call_service", wraps=boundary.client.call_service
        ) as rest,
        pytest.raises(ToolError) as caught,
    ):
        await boundary.tools.ha_call_service(
            domain="light", service="turn_on", entity_id="light.boundary"
        )
    rest.assert_not_awaited()
    assert len(boundary.calls) == 1
    assert boundary.calls[0].context.user_id == hass_admin_user.id
    current = boundary.hass.states.get("light.boundary")
    assert current is not None and current.state == "on"
    result = json.loads(str(caught.value))
    assert result["success"] is False
    assert result["write_outcome_unknown"] is True
    assert result["error"]["code"] == "SERVICE_CALL_FAILED"
    assert result["ha_error_code"] != "unknown_command"
    if failure is HomeAssistantError:
        assert "handler failed after changing the device" in result["error"]["details"]
    else:
        assert "Unknown error" in result["error"]["details"]
    assert "before retrying" in result["error"]["suggestion"]


async def test_lost_reply_is_unknown_not_partial_success(boundary: _Boundary) -> None:
    boundary.drop_reply = True
    with (
        patch.object(
            boundary.client, "call_service", wraps=boundary.client.call_service
        ) as rest,
        pytest.raises(ToolError) as caught,
    ):
        await boundary.tools.ha_call_service(
            domain="light", service="turn_on", entity_id="light.boundary"
        )
    rest.assert_not_awaited()
    assert len(boundary.calls) == 1
    result = json.loads(str(caught.value))
    assert result["success"] is False
    assert result["write_outcome_unknown"] is True
    assert result["ha_error_code"] is None


@pytest.mark.parametrize("refusal", ["unknown_command", "not_sent"])
async def test_proven_no_dispatch_falls_back_exactly_once(
    boundary: _Boundary, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    with patch.object(
        boundary.client, "call_service", wraps=boundary.client.call_service
    ) as rest:
        if refusal == "unknown_command":
            # The real Core router refuses the client's mismatched command name.
            with monkeypatch.context() as route:
                route.setattr(
                    tools_service, "WS_CALL_SERVICE", "ha_mcp_tools/retired_call"
                )
                result = await boundary.tools.ha_call_service(
                    domain="light",
                    service="turn_on",
                    entity_id="light.boundary",
                    wait=False,
                )
        else:
            with patch.object(
                boundary.socket,
                "send_command",
                AsyncMock(side_effect=HomeAssistantCommandNotSent("not sent")),
            ):
                result = await boundary.tools.ha_call_service(
                    domain="light",
                    service="turn_on",
                    entity_id="light.boundary",
                    wait=False,
                )
    assert result["success"] is True
    rest.assert_awaited_once()
    assert len(boundary.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"value": None},
        {},
        {"value": 0},
        {"items": []},
        {"flag": False},
        {"success": False, "error_code": "invalid_format", "error": "service data"},
    ],
)
async def test_accepted_response_payload_is_preserved(
    boundary: _Boundary, payload: ServiceResponse
) -> None:
    boundary.response = payload
    with patch.object(
        boundary.client, "call_service", wraps=boundary.client.call_service
    ) as rest:
        result = await boundary.tools.ha_call_service(
            domain="light",
            service="turn_on",
            entity_id="light.boundary",
            return_response=True,
        )
    rest.assert_not_awaited()
    assert result["success"] is True
    assert result["service_response"] == payload
    assert type(result["service_response"]) is type(payload)
    assert result["verified_state"] == "on"
    assert len(boundary.calls) == 1


async def test_an_unrequested_response_is_not_added(boundary: _Boundary) -> None:
    result = await boundary.tools.ha_call_service(
        domain="light", service="turn_on", entity_id="light.boundary"
    )
    assert result["success"] is True
    assert "service_response" not in result
    assert len(boundary.calls) == 1


async def test_accepted_write_without_confirmation_remains_partial(
    boundary: _Boundary,
) -> None:
    boundary.confirm = False
    with patch.object(
        boundary.client, "call_service", wraps=boundary.client.call_service
    ) as rest:
        result = await boundary.tools.ha_call_service(
            domain="light", service="turn_on", entity_id="light.boundary"
        )
    rest.assert_not_awaited()
    assert result["success"] is True
    assert result["partial"] is True
    assert "write_outcome_unknown" not in result
    assert len(boundary.calls) == 1
    current = boundary.hass.states.get("light.boundary")
    assert current is not None and current.state == "off"
