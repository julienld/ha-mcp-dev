"""Read-only completion signal; starting a manager does not bind its routes."""

from typing import Any


def endpoint_ready(hass: Any, entry: Any) -> bool:
    if not hass.is_running or getattr(entry.state, "value", entry.state) != "loaded":
        return False
    domain = hass.data.get("ha_mcp_tools", {})
    cfg = domain.get("webhook", {})
    webhook_id = entry.data.get("webhook_id")
    registration = hass.data.get("webhook", {}).get(webhook_id, {})
    if (
        not webhook_id
        or cfg.get("webhook_id") != webhook_id
        or registration.get("domain") != "ha_mcp_tools"
        or cfg.get("auth_mode") != entry.options.get("webhook_auth", "none")
    ):
        return False
    mode = cfg["auth_mode"]
    if mode == "ha_auth":
        return cfg.get("resource_server") is not None
    if mode == "legacy":
        return cfg.get("oauth_provider") is not None
    return mode == "none"
