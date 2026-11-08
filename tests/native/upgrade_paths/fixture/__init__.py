"""Read-only upgrade attestation inside disposable Core."""

import hashlib
import json
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .readiness import endpoint_ready


class UpgradeView(HomeAssistantView):
    url = "/api/upgrade_fixture"
    name = "upgrade_fixture:observe"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if not request["hass_user"].is_admin:
            raise web.HTTPForbidden()
        hass = request.app["hass"]
        from custom_components.protocol_fixture.runtime import (
            _manager_entry,
            runtime_proof,
        )

        manager = hass.data.get("ha_mcp_tools", {}).get("manager")
        if manager is None or not manager.is_running:
            return web.json_response({"running": False})
        entry = _manager_entry(hass, manager)
        if not endpoint_ready(hass, entry):
            return web.json_response({"running": False})
        keys = (
            "webhook_id",
            "secret_path",
            "oauth_client_id",
            "oauth_client_secret",
            "oauth_signing_key",
            "dcr_signing_key",
        )
        identity = {
            "entry_ids": sorted(
                e.entry_id for e in hass.config_entries.async_entries("ha_mcp_tools")
            ),
            **{k: entry.data.get(k) for k in keys},
        }
        proof = await hass.async_add_executor_job(runtime_proof, hass)
        proof["identity"] = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        proof["entry_id"] = entry.entry_id
        state = hass.states.get("input_boolean.upgrade_probe")
        proof["witness_state"] = state.state if state else None
        return web.json_response(proof)


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    hass.http.register_view(UpgradeView())
    return True
