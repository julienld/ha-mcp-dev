"""The private loopback client keeps its posture and leaves Core's SDK intact."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Any

import httpx2
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from mcp import McpError, types

from custom_components.ha_mcp_tools import llm_api
from custom_components.ha_mcp_tools.const import EXPOSURE_FULL

from ._llm_api_server import (
    ServedTool,
    api_instance,
    call,
    mirrored_tool,
    payload,
    private_transport,
    serve,
    unused_port,
)

pytestmark = pytest.mark.usefixtures("socket_enabled")


def _watch_transport_clients(
    monkeypatch: pytest.MonkeyPatch, transport: ModuleType
) -> list[Any]:
    """Record the ``http_client`` the component hands the SDK transport."""
    real = transport.streamable_http_client
    handed: list[Any] = []

    def recording(url: str, *, http_client: Any = None, **kwargs: Any) -> Any:
        handed.append(http_client)
        return real(url, http_client=http_client, **kwargs)

    monkeypatch.setattr(transport, "streamable_http_client", recording)
    return handed


def _watch_http_clients(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the constructor arguments of every httpx client built.

    ``verify`` has no public accessor on a constructed client, so pinning it
    needs the call itself. The clients are real subclasses, so the SDK still
    drives a fully working client.
    """
    built: list[dict[str, Any]] = []

    class Spy(httpx2.AsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", Spy)
    return built


class TestLoopbackClient:
    async def test_the_sdk_gets_its_own_client_with_a_generous_timeout(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Home Assistant's shared client carries httpx's 5-second default, and
        the SDK adds no timeout of its own to a client it is handed, so that
        became the real ceiling of every tool call."""
        transport = importlib.import_module("ha_mcp._vendor.mcp.client.streamable_http")
        handed = _watch_transport_clients(monkeypatch, transport)
        built = _watch_http_clients(monkeypatch)

        async with serve() as srv:
            await api_instance(hass, srv.port, EXPOSURE_FULL)

        [client] = handed
        assert client.timeout.read is not None
        assert client.timeout.read >= llm_api.CALL_TOOL_TIMEOUT_SECONDS
        # An environment proxy would both misroute the call and leak the
        # secret path in its URL to the proxy.
        assert client.trust_env is False
        # Loopback is plain HTTP; building a CA bundle would read files on the
        # event loop for nothing.
        assert [b["verify"] for b in built] == [False]
        # Scoped to the one session.
        assert client.is_closed

    async def test_an_environment_proxy_is_not_consulted_for_the_loopback_call(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dead_proxy = f"http://127.0.0.1:{unused_port()}"
        for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(name, dead_proxy)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)

        async with serve() as srv:
            # Control: a client that trusts the environment does take the proxy.
            async with httpx2.AsyncClient() as trusting:
                with pytest.raises(httpx2.HTTPError):
                    await trusting.post(f"http://127.0.0.1:{srv.port}/private_x")

            instance = await api_instance(hass, srv.port, EXPOSURE_FULL)

        assert [tool.name for tool in instance.tools] == ["ha_search"]


class TestSharedTransportIsolation:
    async def test_a_shared_transport_rename_cannot_change_the_private_posture(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A changed shared transport must not redirect the private client."""
        built = _watch_http_clients(monkeypatch)
        current = importlib.import_module("mcp.client.streamable_http")
        pre_rename = ModuleType("mcp.client.streamable_http")
        monkeypatch.setattr(
            pre_rename,
            "streamablehttp_client",
            current.streamablehttp_client,
            raising=False,
        )
        monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", pre_rename)

        async with serve() as srv:
            instance = await api_instance(hass, srv.port, EXPOSURE_FULL)

        assert [tool.name for tool in instance.tools] == ["ha_search"]
        [client] = built
        assert client["trust_env"] is False
        assert client["verify"] is False
        # The SDK always supplies a timeout; None would disable every timeout.
        assert client["timeout"] is not None


class TestPrivateSdk:
    """The component uses its own client while Core provides the real peer."""

    async def test_the_transport_is_given_an_httpx2_client(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = private_transport()
        handed = _watch_transport_clients(monkeypatch, transport)

        async with serve() as srv:
            await api_instance(hass, srv.port, EXPOSURE_FULL)

        [client] = handed
        assert isinstance(client, httpx2.AsyncClient)
        assert client.trust_env is False
        assert client.timeout.read is not None
        assert client.timeout.read >= llm_api.CALL_TOOL_TIMEOUT_SECONDS

    async def test_an_unreachable_server_is_a_transport_failure(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        private_transport()

        with pytest.raises(HomeAssistantError, match="Could not reach"):
            await api_instance(hass, unused_port(), EXPOSURE_FULL)

    async def test_a_protocol_error_is_a_transport_failure(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2.x raises ``MCPError`` where 1.x raised ``McpError``."""
        private_transport()
        error = McpError(types.ErrorData(code=-32000, message="boom"))

        async with serve(list_error=error) as srv:
            with pytest.raises(HomeAssistantError, match="Could not reach"):
                await api_instance(hass, srv.port, EXPOSURE_FULL)

    async def test_tool_schemas_are_read_from_the_2x_field_name(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2.x names the field ``input_schema``; 1.x names it ``inputSchema``."""
        private_transport()

        async with serve() as srv:
            instance = await api_instance(hass, srv.port, EXPOSURE_FULL)

        [search] = instance.tools
        assert search.parameters({"query": "kitchen"}) == {"query": "kitchen"}

    async def test_a_call_result_keeps_the_camel_case_keys(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        private_transport()
        result = types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")],
            structuredContent={"success": True},
            isError=False,
        )

        async with serve([ServedTool(result=result)]) as srv:
            dumped = payload(await call(hass, mirrored_tool(srv.port), {}))

        assert dumped["structuredContent"] == {"success": True}
        assert dumped["isError"] is False
        assert "is_error" not in dumped


class TestPrivateResultAndCoreProvider:
    """Forward wire fields without replacing the shared provider used by Core."""

    @staticmethod
    def _answer() -> types.CallToolResult:
        return types.CallToolResult.model_validate(
            {
                "content": [{"type": "text", "text": "ok"}],
                "structuredContent": {"success": True},
                "isError": False,
                "_meta": {"trace": "t"},
            }
        )

    async def test_forwarding_preserves_wire_keys_and_the_shared_sdk(
        self, hass: HomeAssistant
    ) -> None:
        shared = importlib.import_module("mcp")
        shared_session = importlib.import_module("mcp.client.session")
        async with serve([ServedTool(result=self._answer())]) as srv:
            result = payload(await call(hass, mirrored_tool(srv.port), {}))

        assert set(result) == {"content", "structuredContent", "isError", "meta"}
        assert sys.modules["mcp"] is shared
        assert sys.modules["mcp.client.session"] is shared_session

    async def test_tool_payload_and_metadata_values_are_not_renamed(
        self, hass: HomeAssistant
    ) -> None:
        attributes = {"attributes": {"_meta": 1, "meta": 2}}
        result = types.CallToolResult.model_validate(
            {
                "content": [
                    {"type": "text", "text": "ok", "_meta": {"_meta": "x"}},
                ],
                "structuredContent": attributes,
                "_meta": {"nested": {"_meta": "y"}},
            }
        )

        async with serve([ServedTool(result=result)]) as srv:
            dumped = payload(await call(hass, mirrored_tool(srv.port), {}))

        assert dumped["structuredContent"] == attributes
        assert dumped["meta"] == {"nested": {"_meta": "y"}}
        assert dumped["content"][0]["meta"] == {"_meta": "x"}

    async def test_transport_errors_are_read_without_importing_on_the_loop(
        self, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mapping a failure runs on the event loop, where Home Assistant flags
        an import: the error classes come from what the SDK already loaded."""
        real_import_module = importlib.import_module

        def never_loads(name: str, package: str | None = None) -> Any:
            if name in {"httpx", "httpx2", "mcp"} and name not in sys.modules:
                raise AssertionError(f"imported {name} on the event loop")
            return real_import_module(name, package)

        monkeypatch.setattr(importlib, "import_module", never_loads)

        with pytest.raises(HomeAssistantError, match="Could not reach"):
            await api_instance(hass, unused_port(), EXPOSURE_FULL)
