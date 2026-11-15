"""A service call's response data: Core's reply envelope and its refusals."""

from __future__ import annotations

from typing import Any

from ha_mcp.runtime.action_constants import (
    _COMPONENT_RESPONSE_UNCONFIRMED_WARNING as COMPONENT_RESPONSE_UNCONFIRMED_WARNING,
)
from ha_mcp.runtime.action_constants import (
    _NON_ENVELOPE_WARNING as NON_ENVELOPE_WARNING,
)
from ha_mcp.runtime.action_constants import (
    SERVICE_FAILED_AFTER_DISPATCH_HINT,
)
from ha_mcp.runtime.action_projection import ActionProjection, note_rejected_response

from .component_api import (
    COMPONENT_INSTALL_HINT,
    COMPONENT_VIA_HACS,
    component_supports,
    get_component_caps,
)

#: Added to a failed ``return_response`` call that went to Core's REST API: Core
#: checks the response only after the service ran.
RESPONSE_CALL_FAILED_HINT = (
    "The service may have run before Home Assistant refused its response: check "
    "its effect before calling it again."
)


async def response_call_failed_hint(client: Any, return_response: bool) -> str | None:
    """``RESPONSE_CALL_FAILED_HINT`` for a call that asked for a response.

    Only the component's answer says whether the service ran before a refusal,
    so an installation without it is also told to install it, and one that has
    it to update it if it is older than the server: an outdated component is
    not supported, and it answers such a call as a failed one.
    """
    if not return_response:
        return None
    if component_supports(await get_component_caps(client), "call_service"):
        return (
            f"{RESPONSE_CALL_FAILED_HINT} A current ha_mcp_tools component reports "
            f"a refused response as such: update an older one {COMPONENT_VIA_HACS}"
        )
    return (
        f"{RESPONSE_CALL_FAILED_HINT} The ha_mcp_tools component reports a "
        f"refused response as such. {COMPONENT_INSTALL_HINT}"
    )


split_return_response_envelope = ActionProjection._split_return_response_envelope

__all__ = [
    "COMPONENT_RESPONSE_UNCONFIRMED_WARNING",
    "NON_ENVELOPE_WARNING",
    "RESPONSE_CALL_FAILED_HINT",
    "SERVICE_FAILED_AFTER_DISPATCH_HINT",
    "note_rejected_response",
    "response_call_failed_hint",
    "split_return_response_envelope",
]
