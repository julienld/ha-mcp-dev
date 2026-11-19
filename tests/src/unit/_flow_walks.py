"""The two flow walkers for tests whose walks know no ``FlowRef``.

They keep the raw error and abort keys, and a progress step raises
``ValueError``; a test passes ``flow=`` itself to get Core's text or a poll.
"""

from collections.abc import Awaitable
from typing import Any

from ha_mcp.backends.legacy_flows import legacy_flow
from ha_mcp.runtime.flows import walker

_walk = legacy_flow(walker._handle_flow_steps)
_walk_subentry = legacy_flow(walker._handle_config_subentry_flow_steps)


def _handle_flow_steps(*args: Any, **kwargs: Any) -> Awaitable[Any]:
    return _walk(*args, flow=None, **kwargs)


def _handle_config_subentry_flow_steps(*args: Any, **kwargs: Any) -> Awaitable[Any]:
    return _walk_subentry(*args, flow=None, **kwargs)
