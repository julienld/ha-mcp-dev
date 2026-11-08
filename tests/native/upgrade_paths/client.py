"""Persistent HTTP client configuration; fresh sessions reuse existing credentials."""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

import httpx

from tests.native.protocol_comparison.wire import (
    MAX_BYTES,
    loopback_url,
    modern_request,
    parse_reply,
)

from .contracts import UpgradeFailure


class Client:
    def __init__(self, http: httpx.AsyncClient, connection: dict[str, Any], token: str):
        self.http = http
        self.url = loopback_url(connection["url"])
        self.protocol = connection["protocol"]
        self.token = token
        self.ids = itertools.count(1)
        self.session: str | None = None

    def _headers(self) -> dict[str, str]:
        result = {
            "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": self.protocol,
        }
        if self.token:
            result["Authorization"] = "Bearer " + self.token
        if self.session:
            result["Mcp-Session-Id"] = self.session
        return result

    async def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = next(self.ids)
        headers = self._headers()
        if self.protocol == "2026-07-28":
            stamp, body = modern_request(
                request_id, method, params or {}, self.protocol
            )
            headers.update(stamp)
        else:
            body = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        payload = bytearray()
        async with (
            asyncio.timeout(45),
            self.http.stream("POST", self.url, headers=headers, json=body) as response,
        ):
            if response.status_code != 200:
                raise UpgradeFailure("mcp_http_refused")
            if response.headers.get("Mcp-Session-Id"):
                self.session = response.headers["Mcp-Session-Id"]
            async for chunk in response.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > MAX_BYTES:
                    raise UpgradeFailure("mcp_response_limit")
            parsed = parse_reply(
                response.headers.get("content-type", ""), bytes(payload), request_id
            )
        if "error" in parsed:
            raise UpgradeFailure("mcp_rpc_refused")
        return parsed["result"]

    async def connect(self) -> None:
        if self.protocol == "2026-07-28":
            result = await self.rpc("server/discover")
            if self.protocol not in result.get("supportedVersions", []):
                raise UpgradeFailure("mcp_protocol_not_preserved")
            return
        result = await self.rpc(
            "initialize",
            {
                "protocolVersion": self.protocol,
                "capabilities": {},
                "clientInfo": {"name": "persisted-upgrade-client", "version": "1"},
            },
        )
        if result.get("protocolVersion") != self.protocol:
            raise UpgradeFailure("mcp_protocol_not_preserved")
        response = await self.http.post(
            self.url,
            headers=self._headers(),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        if response.status_code not in {200, 202, 204}:
            raise UpgradeFailure("mcp_initialized_notification_refused")

    async def catalogue(self) -> dict[str, Any]:
        tools = {}
        cursor = None
        for _ in range(32):
            result = await self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            for tool in result["tools"]:
                if tool["name"] in tools:
                    raise UpgradeFailure("duplicate_catalogue_entry")
                tools[tool["name"]] = tool
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
        raise UpgradeFailure("catalogue_page_limit")

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import json

        result = await self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise UpgradeFailure("mcp_tool_refused")
        if result.get("_meta", {}).get("ha_mcp", {}).get("status") in {
            "outcome_unknown",
            "partial",
        }:
            raise UpgradeFailure("mcp_tool_outcome_not_confirmed")
        payload = result.get("structuredContent")
        if payload is None:
            text = next(
                (
                    c["text"]
                    for c in result.get("content", [])
                    if c.get("type") == "text"
                ),
                None,
            )
            payload = json.loads(text) if text is not None else None
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise UpgradeFailure("mcp_tool_result_changed")
        return payload
