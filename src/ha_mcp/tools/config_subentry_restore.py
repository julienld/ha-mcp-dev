"""Legacy exception facade over the shared Core flow implementation."""

import ha_mcp.runtime.flows.subentry_restore as _shared
from ha_mcp.backends.legacy_flows import legacy_helper_flow

_SubentryFlowProgress = _shared._SubentryFlowProgress
_feed_title_as_name = legacy_helper_flow(_shared._feed_title_as_name)
_walk_snapshot = legacy_helper_flow(_shared._walk_snapshot)
recreate_config_subentry = legacy_helper_flow(_shared.recreate_config_subentry)
restore_config_subentry = legacy_helper_flow(_shared.restore_config_subentry)

__all__ = [
    "_feed_title_as_name",
    "_SubentryFlowProgress",
    "_walk_snapshot",
    "recreate_config_subentry",
    "restore_config_subentry",
]
