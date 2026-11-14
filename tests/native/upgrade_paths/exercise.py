"""Black-box client continuity, catalogue and observable service effects."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from .auth import checked, enroll, refresh
from .client import Client
from .contracts import (
    PROTOCOLS,
    UpgradeFailure,
    catalogue_differences,
    fingerprint,
    validate_phase,
)

ENTITY = "input_boolean.upgrade_probe"


async def ready(
    http: httpx.AsyncClient,
    origin: str,
    token: str,
    expected: dict[str, Any],
    runtime: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 720
    while time.monotonic() < deadline:
        try:
            response = await http.get(
                origin + "/api/upgrade_fixture",
                headers={"Authorization": "Bearer " + token},
            )
            if response.status_code not in {200, 404}:
                raise UpgradeFailure(
                    "runtime_probe_http_refused", http_status=response.status_code
                )
            if response.status_code == 200 and (proof := response.json()).get(
                "running"
            ):
                for key in (
                    "run_nonce",
                    "revision",
                    "core_image_id",
                    "component_sha256",
                    "wheel_sha256",
                    "package_sha256",
                ):
                    if proof.get(key) != expected[key]:
                        raise UpgradeFailure("runtime_build_receipt_mismatch")
                if (
                    proof.get("runtime") != runtime
                    or proof.get("entry_runtime") != runtime
                ):
                    raise UpgradeFailure("runtime_mode_changed")
                if not proof.get("component_matches_build") or not proof.get(
                    "package_matches_build"
                ):
                    raise UpgradeFailure("installed_artifacts_changed")
                return proof
        except httpx.TransportError:
            # Core restarts can briefly refuse these read-only readiness probes.
            # Retry only this observation until the deadline; never replay MCP writes.
            pass
        await asyncio.sleep(1)
    raise UpgradeFailure("runtime_startup_timeout")


async def enroll_main(
    http: httpx.AsyncClient,
    origin: str,
    url: str,
    auth: str,
    actor: dict[str, str],
    legacy: dict[str, str],
    path: Path,
) -> tuple[str, dict[str, Any]]:
    identity, grant = await enroll(http, origin, auth, actor, legacy)
    connection = {"url": url, "auth": auth, "oauth": identity, "grant_origin": "main"}
    await asyncio.to_thread(
        path.write_text, json.dumps(connection, sort_keys=True), encoding="utf-8"
    )
    await asyncio.to_thread(path.chmod, 0o600)
    return fingerprint(connection), grant


async def _core_state(client: Client, control: tuple[str, str]) -> str:
    origin, token = control
    state = checked(
        await client.http.get(
            origin + "/api/states/" + ENTITY,
            headers={"Authorization": "Bearer " + token},
        )
    )
    return state["state"]


async def witness(client: Client, *, baseline: bool, control: tuple[str, str]) -> None:
    if not baseline:
        state = await client.call("ha_get_state", {"entity_id": ENTITY})
        if state.get("data", state).get("state") != "on":
            raise UpgradeFailure("persisted_state_lost")
        if await _core_state(client, control) != "on":
            raise UpgradeFailure("persisted_core_state_lost")
    # Each dispatch happens once. A missing reply fails the phase; no replay.
    for service, expected in (("turn_off", "off"), ("turn_on", "on")):
        await client.call(
            "ha_call_service",
            {"domain": "input_boolean", "service": service, "entity_id": ENTITY},
        )
        state = await client.call("ha_get_state", {"entity_id": ENTITY})
        if state.get("data", state).get("state") != expected:
            raise UpgradeFailure("mcp_service_effect_changed")
        if await _core_state(client, control) != expected:
            raise UpgradeFailure("core_service_effect_not_observed")


async def phase(
    http: httpx.AsyncClient,
    path: Path,
    connection_hash: str,
    grant: dict[str, Any],
    proof: dict[str, Any],
    baseline: dict[str, Any] | None,
    catalogues: dict[str, Any],
    *,
    control: tuple[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    connection = json.loads(await asyncio.to_thread(path.read_bytes))
    if fingerprint(connection) != connection_hash:
        raise UpgradeFailure("client_connection_changed")
    result: dict[str, Any] = {
        "passed": False,
        "connection_hash": connection_hash,
        "identity": proof["identity"],
        "grant_origin": connection["grant_origin"],
        "oauth": bool(connection["oauth"]),
        "protocols": {},
        "catalogue_changes": [],
    }
    for protocol in PROTOCOLS:
        client = Client(
            http, {**connection, "protocol": protocol}, grant["access_token"]
        )
        await client.connect()
        catalog = await client.catalogue()
        if baseline is None:
            catalogues[protocol] = catalog
        else:
            result["catalogue_changes"].extend(
                {"protocol": protocol, **delta}
                for delta in catalogue_differences(catalogues[protocol], catalog)
            )
        await witness(client, baseline=baseline is None, control=control)
        result["protocols"][protocol] = True
    result.update(connected=True, witness_preserved=True)
    if result["oauth"]:
        grant = await refresh(http, connection, grant)
        # Refresh success alone is insufficient: its token must still reach MCP.
        renewed = Client(
            http, {**connection, "protocol": PROTOCOLS[0]}, grant["access_token"]
        )
        await renewed.connect()
        await renewed.call("ha_get_state", {"entity_id": ENTITY})
        result["old_grant_refreshed"] = True
    validate_phase(baseline or result, result, connection_hash)
    result["passed"] = not result["catalogue_changes"]
    return result, grant


async def choose_native(
    http: httpx.AsyncClient, origin: str, token: str, entry_id: str, owner: str
) -> None:
    endpoint = origin + "/api/config/config_entries/options/flow"
    headers = {"Authorization": "Bearer " + token}
    form = checked(
        await http.post(endpoint, headers=headers, json={"handler": entry_id})
    )
    if form.get("type") != "form":
        raise UpgradeFailure("native_options_form_unavailable")
    values = {}
    for field in form["data_schema"]:
        if "default" in field:
            values[field["name"]] = field["default"]
        elif "suggested_value" in field.get("description", {}):
            values[field["name"]] = field["description"]["suggested_value"]
    values.update(runtime_mode="native", native_owner_user_id=owner)
    saved = checked(
        await http.post(endpoint + "/" + form["flow_id"], headers=headers, json=values)
    )
    if saved.get("type") != "create_entry":
        raise UpgradeFailure("native_selection_refused")
