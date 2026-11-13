"""Read execution traces through Core owners and their original serializers."""

import json
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from ha_mcp.runtime.progress import report_progress
from ha_mcp.runtime.trace_logbook import TraceLogbook
from ha_mcp.runtime.trace_results import (
    _diagnostic_suggestion,
    _format_detailed_trace,
    _format_trace_list,
    _requested_sections,
    _validate_trace_request,
    trace_target,
)
from ha_mcp.tool_api import CallContext, ToolFailure, UnsupportedOperation
from ha_mcp.utils.owned_executor import await_owned_io

from .registry_access import Authorize, authorize_actor, registry_failure


@dataclass(slots=True)
class TraceTarget:
    entity_id: str | None
    domain: str
    item_id: str | None
    context_id: str | None
    run_id: str | None
    match: dict[str, Any] | None


def _project_trace(
    target: TraceTarget,
    trace_data: Any,
    arguments: dict[str, Any],
    logbook: TraceLogbook | None,
    diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    if not target.run_id:
        return _format_trace_list(
            target.entity_id,
            trace_data,
            arguments.get("limit", 10),
            diagnostics,
            domain=target.domain,
            offset=arguments.get("offset", 0),
            order=arguments.get("order", "newest"),
        )
    result = _format_detailed_trace(
        target.entity_id,
        target.run_id,
        trace_data,
        domain=target.domain,
        item_id=target.item_id,
        sections=arguments.get("sections"),
        logbook=logbook,
    )
    if target.context_id and target.match:
        result.update(
            context_id=target.context_id,
            context_match=target.match["match"],
            context_scanned=target.match["scanned"],
        )
        if target.match.get("other_matches"):
            result["context_other_matches"] = target.match["other_matches"]
    if logbook and logbook.warnings:
        result.setdefault("warnings", []).extend(logbook.warnings)
    return result


@dataclass(slots=True)
class NativeTraces:
    hass: HomeAssistant
    actor: CallContext
    authorize: Authorize = field(kw_only=True, repr=False)

    async def get(self, **arguments: Any) -> dict[str, Any]:
        entity_id = arguments.get("entity_id")
        _validate_trace_request(
            entity_id,
            arguments.get("domain"),
            arguments.get("item_id"),
            arguments.get("context_id"),
            arguments.get("run_id"),
        )
        try:
            await authorize_actor(self.actor, self.authorize)
            await report_progress(
                self.actor.progress,
                progress=0,
                total=3,
                message="resolving trace target",
            )
            target, trace_data = await self._resolve(arguments)
            if not target.run_id and (
                arguments.get("detailed") or arguments.get("sections")
            ):
                raise ToolFailure(
                    "VALIDATION_INVALID_PARAMETER",
                    "sections and detailed require a resolved run",
                    status="not_started",
                )
            await report_progress(
                self.actor.progress, progress=1, total=3, message="fetching trace"
            )
            empty = False
            if trace_data is None:
                encoded, empty = await await_owned_io(
                    self._read(target.domain, target.item_id, target.run_id)
                )
                await authorize_actor(self.actor, self.authorize)
                trace_data = json.loads(encoded)
            logbook = await self._logbook(target, trace_data, arguments)
            diagnostics = (
                await self._diagnostics(entity_id, target.domain)
                if empty and entity_id
                else None
            )
            await authorize_actor(self.actor, self.authorize)
            result = await await_owned_io(
                self.hass.async_add_executor_job(
                    _project_trace,
                    target,
                    trace_data,
                    arguments,
                    logbook,
                    diagnostics,
                )
            )
            await report_progress(
                self.actor.progress, progress=3, total=3, message="trace complete"
            )
            await authorize_actor(self.actor, self.authorize)
            return result
        except ToolFailure:
            raise
        except Exception as error:
            raise registry_failure(error, {"entity_id": entity_id}) from error

    async def _resolve(self, arguments: dict[str, Any]) -> tuple[TraceTarget, Any]:
        entity_id = arguments.get("entity_id")
        domain, item_id = arguments.get("domain"), arguments.get("item_id")
        run_id, context_id = arguments.get("run_id"), arguments.get("context_id")
        if entity_id:
            inferred, object_id = trace_target(entity_id)
            if domain is not None and domain != inferred:
                raise ToolFailure(
                    "VALIDATION_INVALID_PARAMETER",
                    "entity_id and domain disagree",
                    status="not_started",
                )
            domain = inferred
            from homeassistant.helpers import entity_registry as er

            entry = er.async_get(self.hass).async_get(entity_id)
            item_id = (
                str(entry.unique_id)
                if domain == "automation" and entry and entry.unique_id
                else object_id
            )
        match, trace_data = None, None
        if context_id:
            from ..websocket_api.trace_context import _trace_context_prep

            prepared = await _trace_context_prep(
                self.hass,
                {
                    "id": 1,
                    "context_id": context_id,
                    "domain": domain,
                    "item_id": item_id,
                },
            )
            match = json.loads(prepared["payload"])["result"]
            await authorize_actor(self.actor, self.authorize)
            if not match.get("run_id"):
                raise ToolFailure(
                    "RESOURCE_NOT_FOUND",
                    "No stored trace matches this context",
                    status="not_started",
                )
            domain, item_id, run_id = match["domain"], match["item_id"], match["run_id"]
            trace_data = match["trace"]
        if domain is None:
            raise ToolFailure(
                "VALIDATION_INVALID_PARAMETER",
                "A trace domain could not be resolved",
                status="not_started",
            )
        return TraceTarget(
            entity_id, domain, item_id, context_id, run_id, match
        ), trace_data

    async def _logbook(
        self, target: TraceTarget, trace_data: dict[str, Any], arguments: dict[str, Any]
    ) -> TraceLogbook | None:
        sections = _requested_sections(arguments.get("sections"))
        if not target.run_id or (
            "logbook" not in sections
            and not (arguments.get("detailed") and not sections)
        ):
            return None
        from .trace_logbook import trace_logbook

        try:
            logbook = await trace_logbook(self.hass, trace_data)
        except Exception as error:  # noqa: BLE001 - retain the trace when the optional recorder fails
            logbook = TraceLogbook([], None, [f"logbook unavailable: {error}"])
        await authorize_actor(self.actor, self.authorize)
        return logbook

    async def _read(
        self, domain: str, item_id: str | None, run_id: str | None
    ) -> tuple[bytes | str, bool]:
        from homeassistant.components.trace.const import DATA_TRACE, DATA_TRACE_STORE
        from homeassistant.components.trace.util import (
            async_get_trace,
            async_list_traces,
        )
        from homeassistant.helpers.json import ExtendedJSONEncoder, json_bytes

        if DATA_TRACE not in self.hass.data or DATA_TRACE_STORE not in self.hass.data:
            raise UnsupportedOperation("Core trace storage is not loaded")
        key = f"{domain}.{item_id}" if item_id is not None else None
        if run_id:
            try:
                result = await async_get_trace(self.hass, key, run_id)
            except KeyError as error:
                raise ToolFailure(
                    "SERVICE_CALL_FAILED",
                    "The trace could not be found",
                    status="not_started",
                ) from error
            # Serialize live TraceElements on the HA loop, as Core does. Only the
            # detached JSON is decoded/formatted in the executor.
            return json.dumps(result, cls=ExtendedJSONEncoder, allow_nan=False), False
        summaries = await async_list_traces(self.hass, domain, key)
        return json_bytes(summaries), not summaries

    async def _diagnostics(self, entity_id: str, domain: str) -> dict[str, Any]:
        from homeassistant.components.trace.const import CONF_STORED_TRACES
        from homeassistant.helpers import entity_registry as er
        from homeassistant.helpers.json import json_bytes

        state = self.hass.states.get(entity_id)
        diagnostics: dict[str, Any] = {
            "entity_exists": state is not None,
            "entity_enabled": False,
            "entity_state": state.state if state else None,
            "trace_key_available": False,
            "trace_storage_enabled": None,
            "loaded": None,
            "validation": None,
            "references": None,
            "last_triggered": None,
            "suggestion": "",
        }
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is not None:
            diagnostics["entity_exists"] = True
            diagnostics["trace_key_available"] = bool(entry.unique_id)
        if state is not None:
            diagnostics["entity_enabled"] = (
                state.state != "unavailable"
                if domain == "script"
                else state.state == "on"
            )
            diagnostics["last_triggered"] = state.attributes.get("last_triggered")
        if domain == "automation":
            from homeassistant.components.automation import DATA_COMPONENT

            from ..automation_config import async_automation_config

            component = self.hass.data.get(DATA_COMPONENT)
            lookup = await async_automation_config(
                self.hass, {"action": "lookup", "entity_id": entity_id}
            )
            for key in ("loaded", "validation", "references"):
                diagnostics[key] = lookup.get(key)
        else:
            from homeassistant.components.script.const import DOMAIN

            component = self.hass.data.get(DOMAIN)
        entity = component.get_entity(entity_id) if component is not None else None
        trace_config = getattr(entity, "_trace_config", None)
        if trace_config is not None and CONF_STORED_TRACES in trace_config:
            diagnostics["trace_storage_enabled"] = trace_config[CONF_STORED_TRACES] > 0
        diagnostics["suggestion"] = _diagnostic_suggestion(diagnostics, domain)
        result: dict[str, Any] = json.loads(json_bytes(diagnostics))
        return result
