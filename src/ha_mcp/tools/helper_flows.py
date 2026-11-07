"""Legacy compatibility exports from ha_mcp.runtime.helper_flows."""

from ha_mcp.backends.legacy_flows import legacy_helper_flow
from ha_mcp.runtime import helper_flows as _shared

_fetch_helper_flow_types = legacy_helper_flow(_shared._fetch_helper_flow_types)
_fetch_core_helper_domains = legacy_helper_flow(_shared._fetch_core_helper_domains)
_cached = legacy_helper_flow(_shared._cached)
_read = legacy_helper_flow(_shared._read)
helper_flow_types = legacy_helper_flow(_shared.helper_flow_types)
core_helper_domains = legacy_helper_flow(_shared.core_helper_domains)
listed_helper_flows = legacy_helper_flow(_shared.listed_helper_flows)
require_helper_type = legacy_helper_flow(_shared.require_helper_type)
_raise_unknown_helper_type = legacy_helper_flow(_shared._raise_unknown_helper_type)
_TTL_SECONDS = _shared._TTL_SECONDS
_Cache = _shared._Cache
_CACHE = _shared._CACHE
_CORE_CACHE = _shared._CORE_CACHE
