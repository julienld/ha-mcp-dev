"""Core-owned health labels, repair data, startup timings and Matter topology."""

import json
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_bytes

from ha_mcp.runtime.flow_translations import flow_text
from ha_mcp.tool_api import CallContext, ToolFailure
from ha_mcp.utils.owned_executor import await_owned_io

from ..optional_integrations import loaded_integration_module
from .registry_access import Authorize, authorize_actor


class HealthSections:
    hass: HomeAssistant
    actor: CallContext
    authorize: Authorize

    async def _strings(self, domains: set[str], category: str) -> dict[str, str]:
        from homeassistant.helpers.translation import async_get_translations

        await authorize_actor(self.actor, self.authorize)
        result = await await_owned_io(
            async_get_translations(
                self.hass, self.hass.config.language, category, domains
            )
        )
        await authorize_actor(self.actor, self.authorize)
        return result

    async def _health_labels(self, result: dict[str, Any]) -> None:
        info = result.get("health_info") or {}
        if not info:
            return
        try:
            labels = await self._strings(set(info), "system_health")
            titles = await self._strings(set(info), "title")
        except ToolFailure:
            raise
        except Exception:  # noqa: BLE001 - keep the actual health data when strings are unavailable
            result.setdefault("warnings", []).append(
                "Home Assistant's system health labels could not be read"
            )
            return
        for domain, entry in info.items():
            if name := flow_text(titles, domain, "title", None):
                entry["name"] = name
            names = {
                key: text
                for key in entry.get("info") or {}
                if (
                    text := flow_text(labels, domain, f"system_health.info.{key}", None)
                )
            }
            if names:
                entry["labels"] = names

    async def _repair_details(self, section: dict[str, Any]) -> dict[str, Any]:
        from homeassistant.helpers import issue_registry as ir

        issues = section["issues"]
        if not issues:
            return section
        registry = ir.async_get(self.hass)
        strings = await self._strings({issue["domain"] for issue in issues}, "issues")
        untitled = []
        for issue in issues:
            domain, identifier = issue["domain"], issue["issue_id"]
            current = registry.async_get_issue(domain, identifier)
            if current is not None:
                issue["data"] = json.loads(json_bytes(current.data))
            key = f"issues.{issue.get('translation_key') or identifier}"
            for field in ("title", "description"):
                text = flow_text(
                    strings,
                    domain,
                    f"{key}.{field}",
                    issue.get("translation_placeholders"),
                )
                if text is not None:
                    issue[field] = text
            if "title" not in issue:
                untitled.append(f"{domain}.{identifier}")
        if untitled:
            section.setdefault("_warnings", []).append(
                "Home Assistant has no repair strings for these repairs, so they "
                "carry no title: " + ", ".join(untitled)
            )
        return section

    async def _startup(self) -> dict[str, Any]:
        from homeassistant.setup import async_get_setup_timings

        rows: list[dict[str, Any]] = [
            {"domain": domain, "seconds": seconds}
            for domain, seconds in async_get_setup_timings(self.hass).items()
        ]
        rows.sort(key=lambda row: row["seconds"] or 0, reverse=True)
        if rows:
            titles = await self._strings({row["domain"] for row in rows}, "title")
            for row in rows:
                if name := flow_text(titles, row["domain"], "title", None):
                    row["name"] = name
        return {"integrations": rows, "count": len(rows)}

    async def _matter_network(self) -> dict[str, Any]:
        entries = self.hass.config_entries.async_entries("matter")
        entry = next(
            (
                entry
                for entry in entries
                if entry.disabled_by is None and entry.source != "ignore"
            ),
            None,
        )
        if entry is None:
            return {"error": "No enabled Matter config entry found"}
        result: dict[str, Any] = {
            "config_entry": json.loads(json_bytes(entry.as_json_fragment))
        }
        if entry.state is not ConfigEntryState.LOADED:
            return result
        api = loaded_integration_module(self.hass, "matter.api")
        adapter = api.get_matter(self.hass)
        client = adapter.matter_client
        server = client.server_info
        if server is None or server.schema_version < api.TOPOLOGY_SCHEMA_VERSION:
            result["topology"] = {
                "error": "The Matter server does not support network topology"
            }
            return result
        topology = await await_owned_io(client.get_network_topology(refresh=False))
        await authorize_actor(self.actor, self.authorize)
        if (
            self.hass.config_entries.async_get_entry(entry.entry_id) is not entry
            or entry.state is not ConfigEntryState.LOADED
            or api.get_matter(self.hass) is not adapter
            or adapter.matter_client is not client
        ):
            raise ToolFailure(
                "CONFIG_CONFLICT", "Matter owner changed during the health read"
            )
        graph = api._serialize_topology(self.hass, adapter, topology)
        nodes, connections = graph.get("nodes") or [], graph.get("connections") or []
        result["topology"] = {
            **graph,
            "nodes": nodes[:50],
            "connections": connections[:50],
            "node_count": len(nodes),
            "connection_count": len(connections),
        }
        if max(len(nodes), len(connections)) > 50:
            result["topology"]["truncated"] = True
        return result
