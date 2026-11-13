"""Qualified remote device writes, retained for standalone compatibility."""

import logging
from typing import Any

from ha_mcp._vendor.fastmcp.exceptions import ToolError
from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.runtime.device_values import device_update_result
from ha_mcp.runtime.device_values import device_update_values as _device_update_values
from ha_mcp.tools.coercion import parse_string_list_param
from ha_mcp.tools.component_api import UNKNOWN_COMMAND_CODE
from ha_mcp.tools.config_helpers.registry import validate_registry_ids
from ha_mcp.tools.helpers import (
    exception_to_structured_error,
    raise_core_refusal,
    raise_tool_error,
    validate_identifier_not_empty,
)

from .legacy import legacy_errors_sync

logger = logging.getLogger(__name__)
device_update_values = legacy_errors_sync(_device_update_values)


class LegacyDevices:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def _update_device_internal(
        self,
        device_id: str,
        name: str | None = None,
        area_id: str | None = None,
        disabled_by: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Internal implementation of device update."""
        try:
            payload, updates_made = device_update_values(
                device_id,
                name,
                area_id,
                disabled_by,
                labels,
            )
            message = {"type": "config/device_registry/update", **payload}
            area_id = payload.get("area_id")

            # Issue #2159: HA stores an unknown area_id or label_id on the
            # device verbatim. Device labels replace the existing set, so the
            # supplied list is the full set to check; an empty list clears.
            await validate_registry_ids(
                self._client, area_id, labels, None, fail_closed=True
            )

            logger.info(f"Updating device {device_id}: {', '.join(updates_made)}")
            result = await self._client.send_websocket_message(message)

            if not result.get("success"):
                unknown = result.get("error_code") in ("not_found", "unknown_error")
                raise_core_refusal(
                    "Failed to update device",
                    result,
                    {"device_id": device_id},
                    ["Verify the device_id exists using ha_get_device()"]
                    if unknown
                    else None,
                )
            return device_update_result(
                device_id, result.get("result"), updates_made, []
            )

        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error updating device: {e}")
            return exception_to_structured_error(
                e,
                context={"device_id": device_id},
            )

    async def set(
        self,
        device_id: str,
        name: str | None = None,
        area_id: str | None = None,
        disabled_by: str | None = None,
        labels: str | list[str] | None = None,
    ) -> dict[str, Any]:
        parsed_labels = None
        if labels is not None:
            try:
                parsed_labels = parse_string_list_param(labels, "labels")
            except ValueError as e:
                raise_tool_error(
                    create_error_response(
                        ErrorCode.VALIDATION_INVALID_PARAMETER,
                        f"Invalid labels parameter: {e}",
                    )
                )

        # Empty/whitespace device_id would reach the
        # ``config/device_registry/update`` WS message inside
        # ``_update_device_internal`` and surface as a misleading HA
        # "device not found" — same destructive-WS-call class as the
        # ``ha_remove_device`` guard added in this PR.
        validate_identifier_not_empty(
            device_id,
            "device_id",
            suggestions=["Use ha_get_device() to find valid device IDs"],
        )
        return await self._update_device_internal(
            device_id=device_id,
            name=name,
            area_id=area_id,
            disabled_by=disabled_by,
            labels=parsed_labels,
        )

    async def remove(self, device_id: str) -> dict[str, Any]:
        from ha_mcp.tools.tools_registry import _lookup_device_for_remove

        try:
            # Empty/whitespace device_id would surface as a generic
            # "Device not found: " error after a wasted lookup round-trip.
            validate_identifier_not_empty(
                device_id,
                "device_id",
                suggestions=["Use ha_get_device() to find valid device IDs"],
            )
            device = await _lookup_device_for_remove(self._client, device_id)
            result = await self._client.send_websocket_message(
                {"type": "config/device_registry/remove", "device_id": device_id},
                expected_error_codes=frozenset({UNKNOWN_COMMAND_CODE}),
            )
            if result.get("error_code") == UNKNOWN_COMMAND_CODE:
                # Core before 2026.9 has no ``remove``; its predecessor detaches
                # the device's one config entry, which removes the device.
                result = await self._client.send_websocket_message(
                    {
                        "type": "config/device_registry/remove_config_entry",
                        "device_id": device_id,
                        "config_entry_id": device["config_entry_id"],
                    }
                )
            if not result.get("success"):
                raise_core_refusal(
                    "Failed to remove device",
                    result,
                    {"device_id": device_id},
                    [
                        "If the integration does not support removing devices, "
                        "disable the device instead: "
                        "ha_set_device(device_id=..., disabled_by='user')",
                    ],
                )
            return {
                "success": True,
                "device_id": device_id,
                "device_name": device.get("name_by_user") or device.get("name"),
                "message": "Device removed",
            }

        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error removing device: {e}")
            exception_to_structured_error(
                e,
                context={"device_id": device_id},
            )
            return None  # unreachable: exception_to_structured_error always raises
