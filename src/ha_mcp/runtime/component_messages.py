"""Shared component availability guidance without a transport dependency."""

COMPONENT_VIA_HACS = (
    "via HACS (the Marketplace on Home Assistant 2026.11+) and restart Home Assistant."
)

COMPONENT_INSTALL_HINT = (
    f"Install or update the ha_mcp_tools component {COMPONENT_VIA_HACS}"
)


# Said where a state's last_reported comes from REST rather than the component.
REST_LAST_REPORTED_WARNING = (
    "last_reported comes from Home Assistant's REST API, which can keep an "
    "older time while an entity reports an unchanged state "
    "(home-assistant/core#181392); the ha_mcp_tools component serves the live "
    f"value. {COMPONENT_INSTALL_HINT}"
)
