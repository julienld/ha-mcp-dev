"""Enroll once on Main; subsequent phases can only reuse or refresh that grant."""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from tests.native.protocol_comparison.wire import loopback_url

from .contracts import UpgradeFailure

CALLBACK = "http://127.0.0.1:31999/upgrade-callback"


def checked(response: httpx.Response, status: int = 200) -> dict[str, Any]:
    if response.status_code != status:
        raise UpgradeFailure("authentication_http_refused")
    return response.json()


async def enroll(
    http: httpx.AsyncClient,
    origin: str,
    auth: str,
    actor: dict[str, str],
    legacy: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if auth in {"none", "ha-bearer"}:
        return {}, {"access_token": actor["token"] if auth == "ha-bearer" else ""}
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    if auth == "ha-oauth":
        oauth = origin + "/api/ha_mcp_tools/oauth"
        metadata = checked(await http.get(oauth + "/authorization-server"))
        for field in (
            "registration_endpoint",
            "authorization_endpoint",
            "token_endpoint",
        ):
            loopback_url(metadata[field])
            if urlsplit(metadata[field]).netloc != urlsplit(origin).netloc:
                raise UpgradeFailure("oauth_endpoint_escaped_instance")
        registered = checked(
            await http.post(
                metadata["registration_endpoint"],
                json={
                    "client_name": "Persistent upgrade client",
                    "redirect_uris": [CALLBACK],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                },
            ),
            201,
        )
        identity = {
            "client_id": registered["client_id"],
            "token_endpoint": metadata["token_endpoint"],
        }
        authorization = metadata["authorization_endpoint"]
    else:
        identity = {**legacy, "token_endpoint": origin + "/token"}
        authorization = origin + "/authorize"
    params = {
        "client_id": identity["client_id"],
        "redirect_uri": CALLBACK,
        "response_type": "code",
        "state": secrets.token_urlsafe(24),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    response = await http.get(authorization, params=params)
    if auth == "ha-oauth":
        code = await _core_login(http, origin, response, challenge, actor)
    else:
        if response.status_code != 200:
            raise UpgradeFailure("legacy_consent_unavailable")
        consent = await http.post(authorization, data={**params, "action": "approve"})
        if consent.status_code != 302:
            raise UpgradeFailure("legacy_consent_refused")
        target = urlsplit(consent.headers["location"])
        query = parse_qs(target.query)
        if (target.scheme, target.netloc, target.path) != (
            "http",
            "127.0.0.1:31999",
            "/upgrade-callback",
        ) or query.get("state") != [params["state"]]:
            raise UpgradeFailure("legacy_callback_binding_changed")
        code = query["code"][0]
    grant = checked(
        await http.post(
            identity["token_endpoint"],
            data={
                **{k: v for k, v in identity.items() if k != "token_endpoint"},
                "grant_type": "authorization_code",
                "redirect_uri": CALLBACK,
                "code": code,
                "code_verifier": verifier,
            },
        )
    )
    if not grant.get("access_token") or not grant.get("refresh_token"):
        raise UpgradeFailure("main_oauth_grant_incomplete")
    return identity, grant


async def _core_login(
    http: httpx.AsyncClient,
    origin: str,
    response: httpx.Response,
    challenge: str,
    actor: dict[str, str],
) -> str:
    if response.status_code != 302:
        raise UpgradeFailure("ha_oauth_authorize_refused")
    target = urlsplit(loopback_url(response.headers["location"]))
    query = parse_qs(target.query)
    if (
        target.netloc != urlsplit(origin).netloc
        or target.path != "/auth/authorize"
        or query.get("code_challenge") != [challenge]
        or query.get("redirect_uri") != [CALLBACK]
    ):
        raise UpgradeFailure("ha_oauth_translation_changed")
    # Exercise Core's real password login flow and PKCE code store; no
    # fixture-minted authorization code and no browser login after Main.
    started = checked(
        await http.post(
            origin + "/auth/login_flow",
            json={
                "client_id": query["client_id"][0],
                "handler": ["homeassistant", None],
                "redirect_uri": CALLBACK,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
    )
    finished = checked(
        await http.post(
            origin + "/auth/login_flow/" + started["flow_id"],
            json={
                "client_id": query["client_id"][0],
                "username": actor["username"],
                "password": actor["password"],
            },
        )
    )
    if finished.get("type") != "create_entry":
        raise UpgradeFailure("ha_password_login_failed")
    return finished["result"]


async def refresh(
    http: httpx.AsyncClient, connection: dict[str, Any], grant: dict[str, Any]
) -> dict[str, Any]:
    identity = connection["oauth"]
    renewed = checked(
        await http.post(
            identity["token_endpoint"],
            data={
                **{k: v for k, v in identity.items() if k != "token_endpoint"},
                "grant_type": "refresh_token",
                "refresh_token": grant["refresh_token"],
            },
        )
    )
    if not renewed.get("access_token"):
        raise UpgradeFailure("pre_upgrade_grant_cannot_refresh")
    return {**grant, **renewed}
