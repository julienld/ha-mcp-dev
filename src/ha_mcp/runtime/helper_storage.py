"""Storage-helper orchestration over explicit collection operations."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, NoReturn, cast

from ha_mcp.errors import ErrorCode, HomeAssistantError, create_error_response
from ha_mcp.tool_api import BackendTools, ToolFailure
from ha_mcp.utils.registry_update_lock import registry_update_lock

from .errors import raise_failure
from .helper_payload import (
    icon_targets_from_schema,
    merged_update,
    note_hidden_icon,
    note_kept_icon,
    with_create_defaults,
)
from .helper_schema import (
    _CORE_HELPER_SCHEMAS,
    SIMPLE_HELPER_TYPES,
    _helper_response,
    _simple_helper_error_context,
)
from .validation import validate_identifier_not_empty


class HelperStorageTools(BackendTools):
    _check_create_name = True

    async def _require_helper_type(self, helper_type: str) -> None:
        if helper_type in SIMPLE_HELPER_TYPES:
            return
        result = await self.backend.execute(
            "helpers.flow.types", {"helper_type": helper_type}, self.context
        )
        if helper_type not in result["types"]:
            from .helper_flows import _raise_unknown_helper_type

            _raise_unknown_helper_type(helper_type, frozenset(result["types"]))

    async def _validate_action(
        self, action: str | None, helper_id: str | None, helper_type: str
    ) -> str:
        from .helper_validation import _validate_set_helper_action

        return _validate_set_helper_action(action, helper_id, helper_type)

    @asynccontextmanager
    async def _schema_context(
        self, helper_type: str, action: str | None
    ) -> AsyncIterator[None]:
        if helper_type not in SIMPLE_HELPER_TYPES:
            yield
            return
        schemas = await self.backend.execute(
            "helpers.storage.schemas", {}, self.context
        )
        token = _CORE_HELPER_SCHEMAS.set((schemas.get("types", {}), action or "create"))
        try:
            yield
        finally:
            _CORE_HELPER_SCHEMAS.reset(token)

    async def _check_name_collision(
        self, helper_type: str, name: str | None
    ) -> str | None:
        from .flows.session import FlowSession
        from .helper_names import _check_name_collision

        return await _check_name_collision(
            FlowSession(self.backend, self.context), helper_type, name
        )

    async def _validate_registry_ids(
        self,
        area_id: str | None,
        labels: list[str] | None,
        categories: dict[str, str | None],
        *,
        fail_closed: bool,
    ) -> None:
        from .registry_references import validate_registry_ids

        await validate_registry_ids(
            self.backend,
            self.context,
            area_id,
            labels,
            categories,
            fail_closed=fail_closed,
        )

    async def _attach_helper_skill(
        self, response: dict[str, Any], mandatory: bool
    ) -> None:
        from .flows.registry import _attach_helper_skill
        from .flows.session import FlowSession

        await _attach_helper_skill(
            FlowSession(self.backend, self.context), response, mandatory
        )

    async def _create_simple(
        self,
        helper_type: str,
        name: str | None,
        icon: str | None,
        area_id: str | None,
        labels: list[str] | None,
        category: str | None,
        wait: bool,
        MandatoryBPS: bool,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        item_icon, registry_icon = _icon_targets(helper_type, "create", icon)
        body = with_create_defaults(helper_type, fields)
        if name is not None:
            body["name"] = name
        if item_icon:
            body["icon"] = item_icon
        registry = _registry_fields(registry_icon, area_id, labels, category)
        async with registry_update_lock(f"helper_{helper_type}", "create:"):
            if self._check_create_name:
                await self._check_name_collision(helper_type, name)
            result = await self.backend.execute(
                "helpers.storage.write",
                {
                    "helper_type": helper_type,
                    "action": "create",
                    "data": body,
                    "registry": registry,
                    "wait_for_entity": wait,
                },
                self.context,
            )
        response = _write_response(
            result, "create", helper_type, f"Successfully created {helper_type}: {name}"
        )
        await self._note_hidden_icon(response, item_icon)
        await self._attach_helper_skill(response, MandatoryBPS)
        return response

    async def _update_simple(
        self,
        helper_type: str,
        helper_id: str,
        entity_id: str,
        name: str | None,
        icon: str | None,
        area_id: str | None,
        labels: list[str] | None,
        category: str | None,
        wait: bool,
        MandatoryBPS: bool,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        validate_identifier_not_empty(
            helper_id,
            "helper_id",
            message="helper_id is required for update action",
            context=_simple_helper_error_context(helper_type),
        )
        if name is not None and not name.strip():
            raise_failure(
                create_error_response(
                    ErrorCode.VALIDATION_INVALID_PARAMETER,
                    "name cannot be blank. Omit it to keep the current name.",
                    context=_simple_helper_error_context(helper_type),
                )
            )
        async with registry_update_lock(f"helper_{helper_type}", helper_id):
            item = await self._stored_item(helper_type, helper_id, name=name)
            item_icon, registry_icon = _icon_targets(helper_type, "update", icon)
            body = merged_update(
                helper_type,
                item["item"],
                name,
                item_icon,
                fields,
            )
            backup = await self.backend.execute(
                "helpers.backup.capture",
                {
                    **self._backup_identity(helper_type),
                    "helper_type": helper_type,
                    "action": "update",
                    "backup_id": helper_id,
                    "item_id": item["item_id"],
                    "entity_id": item.get("entity_id"),
                    "current_item": item["item"],
                },
                self.context,
            )
            result = await self.backend.execute(
                "helpers.storage.write",
                {
                    "helper_type": helper_type,
                    "action": "update",
                    "item_id": item["item_id"],
                    "data": body,
                    "registry": _registry_fields(
                        registry_icon, area_id, labels, category
                    ),
                    "expected_item": item["item"],
                    **(
                        {"expected_registry": backup["expected_registry"]}
                        if backup and "expected_registry" in backup
                        else {}
                    ),
                    "wait_for_entity": wait,
                },
                self.context,
            )
        response = _write_response(
            result,
            "update",
            helper_type,
            f"Successfully updated {helper_type}: {item.get('entity_id') or helper_id}",
        )
        if backup and backup.get("warnings"):
            response.setdefault("warnings", []).extend(backup["warnings"])
        warnings = list(response.get("warnings") or [])
        note_kept_icon(helper_type, item_icon, result.get("item") or {}, warnings)
        if warnings:
            response["warnings"] = warnings
        await self._note_hidden_icon(response, item_icon)
        await self._attach_helper_skill(response, MandatoryBPS)
        return response

    async def _note_hidden_icon(
        self, response: dict[str, Any], item_icon: str | None
    ) -> None:
        entity_id = response.get("entity_id")
        if item_icon is None or not entity_id:
            return
        try:
            result = await self.backend.execute(
                "entities.registry.read", {"entity_ids": [entity_id]}, self.context
            )
        except HomeAssistantError, ToolFailure, OSError, TimeoutError:
            return  # Advisory read: failure does not undo a successful write.
        entry = result.get("entries", {}).get(entity_id) or {}
        warnings = list(response.get("warnings") or [])
        note_hidden_icon(entity_id, item_icon, entry.get("icon"), warnings)
        if warnings:
            response["warnings"] = warnings

    def _backup_identity(self, helper_type: str) -> dict[str, Any]:
        """Domain wrappers may supply a separately validated backup identity."""
        return {}

    async def _stored_item(
        self, helper_type: str, helper_id: str, *, name: str | None = None
    ) -> dict[str, Any]:
        from .storage_targets import raise_not_stored

        try:
            result = await self.backend.execute(
                "helpers.storage.read",
                {"helper_type": helper_type, "item_id": helper_id},
                self.context,
            )
        except ToolFailure as error:
            if error.code == "ENTITY_NOT_FOUND" and not helper_id.startswith(
                f"{helper_type}."
            ):
                raise_not_stored(helper_type, helper_id, name)
            raise
        if result.get("success") is not True and helper_id.startswith(
            f"{helper_type}."
        ):
            try:
                result = await self.backend.execute(
                    "helpers.storage.read",
                    {"helper_type": helper_type, "entity_id": helper_id},
                    self.context,
                )
            except ToolFailure as error:
                if error.code == "ENTITY_NOT_FOUND" and name:
                    data = cast(dict[str, Any], copy.deepcopy(error.data))
                    data["name"] = name
                    data["error"].setdefault("suggestions", []).append(
                        f"If you meant to create a new helper named {name!r}, "
                        "omit helper_id (or pass action='create')"
                    )
                    raise ToolFailure(
                        error.code, str(error), data=data, status=error.status
                    ) from error
                raise
        if result.get("success") is not True:
            if not helper_id.startswith(f"{helper_type}."):
                raise_not_stored(helper_type, helper_id, name)
            raise_failure(
                create_error_response(
                    ErrorCode.CONFIG_NOT_FOUND,
                    f"{helper_type} config not found for id: {helper_id}",
                    context=_simple_helper_error_context(
                        helper_type, helper_id=helper_id
                    ),
                )
            )
        stored: dict[str, Any] = result
        return stored

    async def _flow_helper(
        self,
        helper_type: str,
        name: str | None,
        helper_id: str | None,
        config: dict[str, Any] | list[dict[str, Any]] | str | None,
        area_id: str | None,
        labels: Any,
        category: str | None,
        wait: bool,
        *,
        icon: str | None,
        action: str | None,
        MandatoryBPS: bool = False,
        flow_id: str | None = None,
        menu_choice: str | None = None,
        abort: bool = False,
    ) -> dict[str, Any]:
        from .flows.helpers import _handle_flow_helper
        from .flows.session import FlowSession
        from .flows.settings import FlowSettings, bind_flow_settings

        session = FlowSession(
            self.backend, self.context, helper_type=helper_type, capture_backup=True
        )
        flags = await self.backend.execute("config.flow.settings", {}, self.context)
        with bind_flow_settings(FlowSettings(lambda: flags["redact_secrets"])):
            response = await _handle_flow_helper(
                session,
                helper_type,
                name,
                helper_id,
                config,
                area_id,
                labels,
                category,
                wait,
                icon=icon,
                action=action,
                MandatoryBPS=MandatoryBPS,
                flow_id=flow_id,
                menu_choice=menu_choice,
                abort=abort,
            )
        if session.warnings:
            response.setdefault("warnings", []).extend(session.warnings)
        return response

    async def _set_config_subentry(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from .flows.helpers import _handle_set_config_subentry
        from .flows.session import FlowSession
        from .flows.settings import FlowSettings, bind_flow_settings

        session = FlowSession(
            self.backend,
            self.context,
            helper_type="config_subentry",
            capture_backup=True,
        )
        flags = await self.backend.execute("config.flow.settings", {}, self.context)
        with bind_flow_settings(FlowSettings(lambda: flags["redact_secrets"])):
            response = await _handle_set_config_subentry(session, *args, **kwargs)
        if session.warnings:
            response.setdefault("warnings", []).extend(session.warnings)
        return response

    def _map_helper_error(
        self, error: Exception, action: str | None, helper_type: str
    ) -> NoReturn:
        raise error


def _icon_targets(
    helper_type: str, action: str, icon: str | None
) -> tuple[str | None, str | None]:
    current = _CORE_HELPER_SCHEMAS.get()
    return icon_targets_from_schema(
        helper_type, action, icon, current[0] if current else None
    )


def _registry_fields(
    icon: str | None,
    area_id: str | None,
    labels: list[str] | None,
    category: str | None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in (
            ("icon", icon),
            ("area_id", area_id),
            ("labels", labels),
            ("category", category),
        )
        if value is not None
    }


def _write_response(
    result: dict[str, Any], action: str, helper_type: str, message: str
) -> dict[str, Any]:
    if result.get("success") is not True:
        error = result.get("error") or {}
        code = (
            ErrorCode.CONFIG_NOT_FOUND
            if error.get("code") == "not_found"
            else ErrorCode.VALIDATION_INVALID_PARAMETER
        )
        raise_failure(
            create_error_response(
                code,
                f"Failed to {action} {helper_type}: {error.get('message', 'unknown error')}",
                context=_simple_helper_error_context(helper_type),
            )
        )
    return _helper_response(
        action,
        helper_type,
        data={**(result.get("item") or {}), **(result.get("registry_applied") or {})},
        entity_id=result.get("entity_id"),
        message=message,
        warnings=list(result.get("warnings") or []),
    )
