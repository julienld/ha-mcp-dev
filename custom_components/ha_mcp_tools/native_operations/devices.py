"""Canonical device writes use the actual registry and integration callbacks."""

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from ha_mcp.runtime.device_values import device_update_result, device_update_values
from ha_mcp.runtime.mutation_guard import check_mutation_admission
from ha_mcp.runtime.registry_references import (
    _raise_if_unknown_area,
    _raise_if_unknown_labels,
)
from ha_mcp.runtime.snapshot_payloads import InvalidBackupSnapshotError
from ha_mcp.runtime.validation import validate_identifier_not_empty
from ha_mcp.tool_api import CallContext, ToolFailure, UnsupportedOperation
from ha_mcp.utils.config_hash import json_values_equal
from ha_mcp.utils.owned_executor import await_owned_io
from ha_mcp.utils.registry_update_lock import registry_update_lock

from .command_validation import _validated_payload
from .device_registry_compat import is_composite_device, registered_device
from .device_updates import commit_device_update, prepare_device_update
from .registry_access import (
    Authorize,
    Capture,
    admit_registry_write,
    authorize_actor,
    capture_registry_before,
    registry_failure,
    registry_json,
)
from .registry_failures import registry_outcome_unknown, registry_target_missing

_CURRENT = object()


@dataclass(slots=True)
class NativeDevices:
    hass: HomeAssistant
    actor: CallContext
    authorize: Authorize = field(kw_only=True, repr=False)
    backup: Capture | None = field(default=None, kw_only=True, repr=False)

    def _owner(self) -> Any:
        from homeassistant.helpers import device_registry as dr

        return dr.async_get(self.hass)

    @staticmethod
    def _target(registry: Any, device_id: str) -> Any:
        if is_composite_device(registry, device_id):
            raise ToolFailure(
                "SERVICE_CALL_FAILED",
                "Cannot change a composite device; select an underlying device.",
                status="not_started",
            )
        device = registered_device(registry, device_id)
        if device is None:
            registry_target_missing("device", device_id)
        return device

    def _check_references(self, payload: dict[str, Any]) -> None:
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import label_registry as lr

        if payload.get("area_id"):
            _raise_if_unknown_area(
                [
                    {"area_id": row.id}
                    for row in ar.async_get(self.hass).async_list_areas()
                ],
                payload["area_id"],
            )
        if payload.get("labels"):
            _raise_if_unknown_labels(
                [
                    {"label_id": row.label_id}
                    for row in lr.async_get(self.hass).async_list_labels()
                ],
                payload["labels"],
            )

    def _check_current(
        self, registry: Any, device_id: str, before: dict[str, Any]
    ) -> Any:
        current_owner = self._owner()
        current = self._target(current_owner, device_id)
        if current_owner is not registry or not json_values_equal(
            registry_json(current.dict_repr), before
        ):
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "The device changed after its before-image was read; no further mutation was sent.",
                status="not_started",
            )
        return current

    async def set(
        self,
        device_id: str,
        name: str | None = None,
        area_id: str | None = None,
        disabled_by: str | None = None,
        labels: str | list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            await admit_registry_write(self.actor, self.authorize)
            validate_identifier_not_empty(device_id, "device_id")
            payload, updates = device_update_values(
                device_id, name, area_id, disabled_by, labels
            )
            row, warnings = await self._update(payload)
            if (
                "disabled_by" in payload
                and payload["disabled_by"] is None
                and row.get("disabled_by") is not None
            ):
                warnings.append(
                    "Core kept the device disabled. Its parent device or config entry may still be disabled."
                )
            return device_update_result(device_id, row, updates, warnings)
        except Exception as error:
            raise registry_failure(error, {"device_id": device_id}) from error

    async def _update(
        self,
        payload: dict[str, Any],
        *,
        expected: Any = _CURRENT,
        capture: bool = True,
    ) -> tuple[dict[str, Any], list[str]]:

        device_id = payload["device_id"]
        async with registry_update_lock("device", device_id):
            registry = self._owner()
            device = self._target(registry, device_id)
            before = registry_json(device.dict_repr)
            if expected is not _CURRENT and not json_values_equal(before, expected):
                raise ToolFailure(
                    "CONFIG_CONFLICT",
                    "The device changed after its restore safety capture.",
                    status="not_started",
                )
            validated = _validated_payload(
                self.hass, "config/device_registry/update", payload
            )
            self._check_references(validated)
            warnings = (
                await capture_registry_before(
                    self.backup,
                    self.actor,
                    "device",
                    device_id,
                    before,
                    "ha_set_device",
                )
                if capture
                else []
            )
            await admit_registry_write(self.actor, self.authorize)
            device = self._check_current(registry, device_id, before)
            self._check_references(validated)
            validated = prepare_device_update(self.hass, validated)
            check_mutation_admission(self.actor)
            try:
                row = commit_device_update(registry, device, validated)
                return row, warnings
            except Exception as error:  # noqa: BLE001 - owner/listeners/serializer may fail after mutation
                return registry_outcome_unknown("device", "update", error)

    async def remove(self, device_id: str) -> dict[str, Any]:
        try:
            await admit_registry_write(self.actor, self.authorize)
            validate_identifier_not_empty(device_id, "device_id")
            async with registry_update_lock("device", device_id):
                return await self._remove(device_id)
        except Exception as error:
            raise registry_failure(error, {"device_id": device_id}) from error

    async def _remove(self, device_id: str) -> dict[str, Any]:
        from homeassistant import loader

        registry = self._owner()
        device = self._target(registry, device_id)
        command = "config/device_registry/remove"
        payload = {"device_id": device_id}
        _validated_payload(self.hass, command, payload)
        before = registry_json(device.dict_repr)
        entry = self.hass.config_entries.async_get_entry(device.config_entry_id)
        if entry is None:
            raise ToolFailure(
                "RESOURCE_NOT_FOUND", "Unknown config entry", status="not_started"
            )
        if not entry.supports_remove_device:
            raise ToolFailure(
                "SERVICE_CALL_FAILED",
                "Config entry does not support device removal",
                status="not_started",
            )
        try:
            integration = await loader.async_get_integration(self.hass, entry.domain)
            component = await integration.async_get_component()
        except (ImportError, loader.IntegrationNotFound) as error:
            raise ToolFailure(
                "SERVICE_CALL_FAILED", "Integration not found", status="not_started"
            ) from error
        await admit_registry_write(self.actor, self.authorize)
        self._check_current(registry, device_id, before)
        if self.hass.config_entries.async_get_entry(entry.entry_id) is not entry:
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "The owning config entry changed during preparation.",
                status="not_started",
            )
        warnings = await capture_registry_before(
            self.backup, self.actor, "device", device_id, before, "ha_remove_device"
        )
        await self._dispatch_remove(component, registry, entry, device, before)
        result = {
            "success": True,
            "device_id": device_id,
            "device_name": before.get("name_by_user") or before.get("name"),
            "message": "Device removed",
        }
        if warnings:
            result["warnings"] = warnings
        return result

    def _remove_target(
        self, registry: Any, entry: Any, device: Any, before: dict[str, Any]
    ) -> Any:
        device = self._check_current(registry, device.id, before)
        if self.hass.config_entries.async_get_entry(entry.entry_id) is not entry:
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "The owning config entry changed before dispatch.",
                status="not_started",
            )
        if not entry.supports_remove_device:
            raise ToolFailure(
                "SERVICE_CALL_FAILED",
                "Config entry no longer supports device removal",
                status="not_started",
            )
        return device

    async def _dispatch_remove(
        self,
        component: Any,
        registry: Any,
        entry: Any,
        device: Any,
        before: dict[str, Any],
    ) -> None:
        from homeassistant.components.config import device_registry as core
        from homeassistant.components.websocket_api.connection import (
            ActiveConnection,
            current_connection,
        )
        from homeassistant.components.websocket_api.http import WebSocketAdapter

        handler = inspect.unwrap(core.websocket_remove_device)
        if not inspect.iscoroutinefunction(handler):
            raise UnsupportedOperation("devices.remove.core_owner")
        if self.actor.user_id is None:
            raise ToolFailure(
                "AUTH_FORBIDDEN",
                "A human administrator is required.",
                status="not_started",
            )
        user = await self.hass.auth.async_get_user(self.actor.user_id)
        if user is None:
            raise ToolFailure(
                "AUTH_FORBIDDEN",
                "The device caller no longer exists.",
                status="not_started",
            )
        replies: list[bytes | str | dict[str, Any]] = []
        token = current_connection.set(None)
        try:
            connection = ActiveConnection(
                WebSocketAdapter(
                    logging.getLogger(__name__), {"connid": "native-device-removal"}
                ),
                self.hass,
                replies.append,
                user,
                None,
                None,
            )
            await admit_registry_write(self.actor, self.authorize)
            self._remove_target(registry, entry, device, before)
            payload = _validated_payload(
                self.hass, "config/device_registry/remove", {"device_id": device.id}
            )
            try:
                # One admitted Core command owns the integration callback and
                # removal. There is no second mutation orchestrated by Native.
                await await_owned_io(
                    handler(
                        self.hass,
                        connection,
                        {"id": 1, "type": "config/device_registry/remove", **payload},
                    )
                )
                if not any(
                    isinstance(reply, dict) and reply.get("success") is True
                    for reply in replies
                ):
                    raise RuntimeError("Core did not confirm the device removal")
                await authorize_actor(self.actor, self.authorize)
                if self._owner().async_get(device.id) is not None:
                    raise RuntimeError("The removed device is still registered")
            except Exception as error:  # noqa: BLE001 - Core may already have dispatched the integration callback
                registry_outcome_unknown("device", "remove", error)
        finally:
            current_connection.reset(token)

    async def read_snapshot(self, device_id: str) -> dict[str, Any] | None:
        await authorize_actor(self.actor, self.authorize)
        registry = self._owner()
        if registry.async_get(device_id) is None:
            return None
        return registry_json(self._target(registry, device_id).dict_repr)

    async def restore_snapshot(
        self,
        device_id: str,
        config: dict[str, Any],
        expected: Any,
    ) -> dict[str, Any]:
        await admit_registry_write(self.actor, self.authorize)
        if config.get("id") != device_id:
            raise InvalidBackupSnapshotError(
                "Device snapshot does not match its identity"
            )
        row, _ = await self._update(
            {
                "device_id": device_id,
                "name_by_user": config.get("name_by_user"),
                "area_id": config.get("area_id"),
                "disabled_by": config.get("disabled_by"),
                "labels": config.get("labels", []),
            },
            expected=expected,
            capture=False,
        )
        return row
