"""Native service outcomes come from Core's execution and response validation."""

from typing import Any

import pytest
from homeassistant.auth.models import User
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.runtime.action_constants import SERVICE_FAILED_AFTER_DISPATCH_HINT
from ha_mcp.runtime.actions import ServiceCallTools
from ha_mcp.tool_api import CallContext, ToolFailure

from ._native_core_backend import backend as backend


@pytest.mark.parametrize("outcome", ["valid", "rejected", "failed"])
async def test_native_service_response_preserves_effect_and_never_replays(
    hass: HomeAssistant,
    hass_admin_user: User,
    backend: NativeBackend,
    outcome: str,
) -> None:
    calls: list[ServiceCall] = []

    async def execute(call: ServiceCall) -> ServiceResponse:
        calls.append(call)
        hass.states.async_set(
            "sensor.native_effect", str(len(calls)), context=call.context
        )
        if outcome == "failed":
            raise HomeAssistantError("handler failed after changing state")
        if outcome == "valid":
            return {"nested": {"zero": 0, "false": False, "empty": []}}
        return None

    hass.services.async_register(
        "counter", "native_effect", execute, supports_response=SupportsResponse.OPTIONAL
    )
    tools = ServiceCallTools(backend, CallContext(hass_admin_user.id))
    arguments: dict[str, Any] = {
        "domain": "counter",
        "service": "native_effect",
        "return_response": True,
    }
    if outcome == "failed":
        with pytest.raises(ToolFailure) as caught:
            await tools.ha_call_service(**arguments)
        assert caught.value.status == "outcome_unknown"
        assert SERVICE_FAILED_AFTER_DISPATCH_HINT in str(caught.value.data)
    else:
        result = await tools.ha_call_service(**arguments)
        assert result["success"] is True
        if outcome == "valid":
            assert result["service_response"] == {
                "nested": {"zero": 0, "false": False, "empty": []}
            }
        else:
            assert result["service_response"] is None
            assert (
                result["response_error"]["translation_key"] == "service_reponse_invalid"
            )
            assert any(
                "Do not call it again" in warning for warning in result["warnings"]
            )
        assert [row["entity_id"] for row in result["result"]] == [
            "sensor.native_effect"
        ]

    state = hass.states.get("sensor.native_effect")
    assert state is not None and state.state == "1"
    assert len(calls) == 1
    assert calls[0].context.user_id == hass_admin_user.id
