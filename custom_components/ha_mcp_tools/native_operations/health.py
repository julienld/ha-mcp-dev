"""Canonical system-health reads through the registered Core owners."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_bytes

from ha_mcp.runtime.health_results import (
    HealthResults,
    dead_entities_result,
    repair_section,
    zha_network_result,
    zwave_network_result,
)
from ha_mcp.tool_api import CallContext, ToolFailure, UnsupportedOperation
from ha_mcp.utils.owned_executor import await_owned_io

from .health_info import read_health_info
from .health_radios import thread_status, zwave_status
from .health_sections import HealthSections
from .radio_access import RadioSession
from .radio_thread import handle_thread
from .registry_access import Authorize, authorize_actor, registry_failure
from .supervisor_access import SupervisorAccess


@dataclass(slots=True)
class NativeHealth(HealthSections, HealthResults):
    hass: HomeAssistant
    actor: CallContext
    authorize: Authorize = field(kw_only=True, repr=False)

    manager: Any = field(default=None, kw_only=True, repr=False)

    async def get(
        self, include: str | None = None, include_dismissed_repairs: bool = False
    ) -> dict[str, Any]:
        try:
            await authorize_actor(self.actor, self.authorize)
            includes = self._parse_includes(include)
            try:
                result = await read_health_info(self.hass, self.actor, self.authorize)
                await self._health_labels(result)
            except UnsupportedOperation:
                if not includes:
                    raise
                result = {
                    "success": True,
                    "baseline_available": False,
                    "health_info": {},
                    "component_count": 0,
                    "message": "System health baseline unavailable.",
                    "warnings": [
                        "The system_health integration is not loaded; returning independently available Core sections."
                    ],
                }
            self._warn_unknown_includes(result, includes)
            sections = self._sections(
                includes, self._snapshot(includes), bool(include_dismissed_repairs)
            )
            values = await await_owned_io(
                asyncio.gather(
                    *(self._section(name, read) for name, read in sections),
                    return_exceptions=True,
                )
            )
            for (name, _read), value in zip(sections, values, strict=True):
                if isinstance(value, BaseException):
                    raise value
                if warnings := value.pop("_warnings", None):
                    result.setdefault("warnings", []).extend(warnings)
                result[name] = value
            await authorize_actor(self.actor, self.authorize)
            return result
        except Exception as error:
            raise registry_failure(error, {"include": include}) from error

    def _snapshot(self, includes: set[str]) -> dict[str, Any] | Exception:
        if not includes.intersection(
            {"repairs", "zwave_network", "matter_network", "dead_entities"}
        ):
            return {}
        from ..websocket_api.system import _do_system_snapshot

        try:
            captured = _do_system_snapshot(
                self.hass,
                {
                    "include_issues": "repairs" in includes,
                    "include_config_entries": bool(
                        includes.intersection(
                            {"zwave_network", "matter_network", "dead_entities"}
                        )
                    ),
                    "include_entities": "dead_entities" in includes,
                    "include_states": "dead_entities" in includes,
                },
            )
            result: dict[str, Any] = json.loads(json_bytes(captured))
            return result
        except Exception as error:  # noqa: BLE001 - preserve acquisition failure for dependent sections
            return error

    def _sections(
        self,
        includes: set[str],
        snapshot: dict[str, Any] | Exception,
        include_dismissed: bool,
    ) -> list[tuple[str, Callable[[], Awaitable[dict[str, Any]]]]]:
        sections: list[tuple[str, Callable[[], Awaitable[dict[str, Any]]]]] = []
        if "repairs" in includes:
            sections.append(
                ("repairs", lambda: self._repairs(snapshot, include_dismissed))
            )
        if includes.intersection({"zha_network", "zha_network_full"}):
            sections.append(
                ("zha_network", lambda: self._zha("zha_network_full" in includes))
            )
        if "zwave_network" in includes:
            sections.append(("zwave_network", lambda: self._zwave(snapshot)))
        if "thread_network" in includes:
            sections.append(("thread_network", self._thread))
        if "matter_network" in includes:
            sections.append(("matter_network", lambda: self._matter(snapshot)))
        if "integration_startup" in includes:
            sections.append(("integration_startup", self._startup))
        if "supervisor" in includes:
            sections.append(("supervisor", self._supervisor))
        if "dead_entities" in includes:
            sections.append(("dead_entities", lambda: self._dead(snapshot)))
        if "config_check" in includes:
            sections.append(("config_check", self._config_check))
        return sections

    async def _section(
        self, name: str, read: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        try:
            await authorize_actor(self.actor, self.authorize)
            result = await read()
            await authorize_actor(self.actor, self.authorize)
            return result
        except ToolFailure as error:
            if error.code == "AUTH_FORBIDDEN":
                raise
            return {
                **_empty_section(name),
                "error": str(error),
                "error_code": error.code,
            }
        except Exception as error:  # noqa: BLE001 - independent health sections embed provider failures
            return {**_empty_section(name), "error": f"{name} not available: {error}"}

    @staticmethod
    def _rows(snapshot: dict[str, Any] | Exception, name: str) -> list[dict[str, Any]]:
        if isinstance(snapshot, Exception):
            raise snapshot
        result: list[dict[str, Any]] = snapshot[name]
        return result

    async def _repairs(
        self, snapshot: dict[str, Any] | Exception, dismissed: bool
    ) -> dict[str, Any]:
        return await self._repair_details(
            repair_section(self._rows(snapshot, "issues"), dismissed)
        )

    async def _zha(self, full: bool) -> dict[str, Any]:
        from ..native_registry_ops import _zha_devices

        rows = await await_owned_io(_zha_devices(self.hass, {}))
        return zha_network_result(json.loads(json_bytes(rows)), full)

    async def _zwave(self, snapshot: dict[str, Any] | Exception) -> dict[str, Any]:
        entry = next(
            (
                row
                for row in self._rows(snapshot, "config_entries")
                if row.get("domain") == "zwave_js"
            ),
            None,
        )
        if entry is None:
            raise ToolFailure("RADIO_UNAVAILABLE", "Z-Wave JS integration not found")
        value = await zwave_status(
            self.hass, entry["entry_id"], self.actor, self.authorize
        )
        return zwave_network_result(json.loads(json_bytes(value)))

    async def _thread(self) -> dict[str, Any]:
        datasets = await self._section("datasets", self._thread_datasets)
        routers = await self._section("border_routers", self._thread_routers)
        result: dict[str, Any] = {}
        if "error" in datasets:
            result["datasets_error"] = (
                f"Thread datasets not available: {datasets['error']}"
            )
        else:
            result["datasets"] = datasets["datasets"]
        if "error" in routers:
            result["border_routers_error"] = (
                f"OTBR border routers not available: {routers['error']}"
            )
        else:
            result["border_routers"] = routers["border_routers"]
        return result

    async def _thread_datasets(self) -> dict[str, Any]:
        session = RadioSession(self.hass, self.actor, self.authorize)
        result = await handle_thread(session, "list_datasets", {})
        session.verify()
        datasets: dict[str, Any] = result["datasets"]
        return datasets

    async def _thread_routers(self) -> dict[str, Any]:
        result = await thread_status(self.hass, self.actor, self.authorize)
        return {"border_routers": list(result.values())}

    async def _matter(self, snapshot: dict[str, Any] | Exception) -> dict[str, Any]:
        return await self._matter_network()

    async def _dead(self, snapshot: dict[str, Any] | Exception) -> dict[str, Any]:
        entries = self._rows(snapshot, "config_entries")
        rows = self._rows(snapshot, "entities")
        states = {
            state["entity_id"]: state
            for state in self._rows(snapshot, "states")
            if isinstance(state, dict) and state.get("entity_id")
        }
        live = (
            {entry["entry_id"] for entry in entries if entry.get("entry_id")}
            if entries
            else None
        )
        result: dict[str, Any] = await await_owned_io(
            self.hass.async_add_executor_job(dead_entities_result, states, rows, live)
        )
        result["config_entries_checked"] = bool(entries)
        if not entries:
            result["_warnings"] = [
                "No integrations are configured; config_entry_orphans detection was skipped. stale_restored was still computed."
            ]
        return result

    async def _supervisor(self) -> dict[str, Any]:
        if "hassio" not in self.hass.config.components:
            return {"error": "Supervisor is not available on this installation"}
        access = SupervisorAccess(self.manager, self.actor)
        result: dict[str, Any] = {}
        for name, path in (
            ("resolution", "/resolution/info"),
            ("core_stats", "/core/stats"),
            ("supervisor_stats", "/supervisor/stats"),
        ):
            try:
                result[name] = await access._read(path)
            except ToolFailure as error:
                if error.code == "AUTH_FORBIDDEN":
                    raise
                result[name] = {"error": str(error)}
        return result

    async def _config_check(self) -> dict[str, Any]:
        from homeassistant.helpers import check_config

        checked = await await_owned_io(
            check_config.async_check_ha_config_file(self.hass)
        )
        return {
            "result": "invalid" if checked.errors else "valid",
            "errors": checked.error_str or None,
            "warnings": checked.warning_str or None,
        }


def _empty_section(name: str) -> dict[str, Any]:
    if name == "repairs":
        return {"issues": [], "count": 0}
    if name == "zha_network":
        return {"devices": [], "count": 0, "total_count": 0}
    if name == "zwave_network":
        return {"controller": {}, "nodes": [], "count": 0, "total_count": 0}
    if name == "thread_network":
        return {"border_routers": [], "count": 0}
    if name == "themes":
        return {
            "themes": [],
            "count": 0,
            "default_theme": None,
            "default_dark_theme": None,
        }
    if name == "config_check":
        return {"result": "unknown", "is_valid": False, "errors": []}
    return {}
