"""Compatibility exports for the canonical transport-neutral HA errors."""

from ha_mcp.errors import (
    HomeAssistantAdminRequiredError,
    HomeAssistantAPIError,
    HomeAssistantAuthError,
    HomeAssistantCommandError,
    HomeAssistantCommandNotSent,
    HomeAssistantCommandTimeout,
    HomeAssistantConnectionError,
    HomeAssistantError,
)

__all__ = [
    "HomeAssistantAdminRequiredError",
    "HomeAssistantAPIError",
    "HomeAssistantAuthError",
    "HomeAssistantCommandError",
    "HomeAssistantCommandNotSent",
    "HomeAssistantCommandTimeout",
    "HomeAssistantConnectionError",
    "HomeAssistantError",
]
