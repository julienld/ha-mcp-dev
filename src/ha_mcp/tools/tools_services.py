"""
Service discovery tools for Home Assistant MCP server.

This module provides service listing and discovery capabilities,
allowing AI to explore available Home Assistant services/actions.
"""

import logging
from collections.abc import Mapping
from typing import Any

from ha_mcp._vendor.fastmcp.tools import tool

from ..backends.legacy import LegacyBackendTools, legacy_errors
from ..client.rest_client import (
    HomeAssistantAPIError,
    HomeAssistantAuthError,
    HomeAssistantCommandError,
    HomeAssistantCommandTimeout,
    HomeAssistantConnectionError,
)
from ..client.websocket_client import get_websocket_client
from ..runtime.services import ServiceDiscoveryTools as SharedServiceDiscoveryTools
from .component_api import (
    component_supports,
    get_component_caps,
    invalidate_caps,
    is_unknown_command,
)
from .flow_translations import configured_language
from .helpers import (
    log_tool_usage,
    register_tool_methods,
)
from .tool_hints import read_only_hints

logger = logging.getLogger(__name__)

# WS command name for the component's domain-scoped Core service catalog read.
WS_SERVICES_LIST = "ha_mcp_tools/services_list"


class ServiceDiscoveryTools(LegacyBackendTools, SharedServiceDiscoveryTools):
    """Remote compatibility wrapper around the shared implementation."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)

    async def _fetch_catalog(
        self, domain: str | None, warnings: list[str]
    ) -> tuple[Any, dict[str, Any]]:
        return await _fetch_catalog_and_translations(self._client, domain, warnings)

    ha_list_services = tool(
        name="ha_list_services",
        tags={"Service & Device Control"},
        annotations=read_only_hints("List Available Services", open_world=False),
    )(
        log_tool_usage(
            legacy_errors(
                SharedServiceDiscoveryTools.ha_list_services,
                suggestions=[
                    "Check Home Assistant connection",
                    "Verify WebSocket API is available",
                    "Try with a specific domain filter",
                ],
            )
        )
    )


def register_services_tools(mcp: Any, client: Any, **kwargs: Any) -> None:
    """Register service discovery tools with the MCP server."""
    register_tool_methods(mcp, ServiceDiscoveryTools(client))


async def _fetch_catalog_and_translations(
    client: Any, domain: str | None, warnings: list[str] | None = None
) -> tuple[Any, dict[str, Any]]:
    """The ``(rest_services, translations)`` pair ``_process_services`` consumes.

    Tries the component (``domain``-scoped, one frame) first; falls back to the
    legacy REST ``get_services()`` + WS ``frontend/get_translations`` pair on any
    capability miss or fallback-eligible error. Both sources are Core's own
    ``async_get_all_descriptions`` output, so the server's shaping runs unchanged
    over either.
    """
    component_payload = await _fetch_services_list_via_component(client, domain=domain)
    if component_payload is not None:
        return component_payload["services"], component_payload["translations"]
    language, language_warning = await configured_language(
        client, "service descriptions"
    )
    if language_warning and warnings is not None:
        warnings.append(language_warning)
    rest_services = await client.get_services()
    translations = await _get_service_translations(client, language, warnings)
    return rest_services, translations


async def _fetch_services_list_via_component(
    client: Any, *, domain: str | None
) -> dict[str, Any] | None:
    """One ``ha_mcp_tools/services_list`` read; ``None`` ⇒ run the legacy path.

    Returns ``{"services": [...], "translations": {...}}`` — ``services`` is the
    REST ``/api/services`` list shape and ``translations`` the same flat
    ``frontend/get_translations`` resources map ``_get_service_translations``
    returns — so ``_process_services`` consumes either source unchanged.

    The command accepts only ``domain`` and an optional ``language``. This
    consumer threads ``domain`` alone (an exact match, identical semantics on
    both sides). ``query`` is not a command parameter: the exact
    concatenation-based filter stays here in ``_process_services``, applied to
    the full domain-scoped catalog, so ``domains`` still lists every domain that
    passes ``domain_filter``. ``language`` is not sent either — the component
    resolves ``hass.config.language`` itself, and an explicit wire value would
    override the instance's configured language. ``None`` on capability
    miss, downgrade (``unknown_command`` → invalidate the cached caps), or
    command error/timeout (logged) — the caller falls back to the legacy REST +
    WS translations fetch.

    Per the uniform transport-fallback taxonomy, a connection-establishment
    failure IS caught here and mapped to ``None`` (legacy fallback), like every
    component fetch helper. This tool's legacy path is the REST ``get_services()`` +
    a per-request WS bridge for translations, NOT the shared pooled WS — so a WS
    outage must not kill the tool when REST can still serve the catalog. The
    catch stays broad so no unexpected fault escapes and kills the tool; routing
    any
    non-command component failure back to the REST catalog fetch is safe here
    (mirrors ``get_component_caps``' own broad-catch precedent).
    """
    caps = await get_component_caps(client)
    if not component_supports(caps, "services_list"):
        return None
    kwargs: dict[str, Any] = {}
    if domain is not None:
        kwargs["domain"] = domain
    try:
        ws = await get_websocket_client(
            url=client.base_url,
            token=client.token,
            verify_ssl=getattr(client, "verify_ssl", None),
        )
        raw = await ws.send_command(WS_SERVICES_LIST, **kwargs)
    except (HomeAssistantCommandError, HomeAssistantCommandTimeout) as exc:
        if is_unknown_command(exc):
            invalidate_caps(client)
        else:
            logger.warning("%s failed; fell back to legacy: %r", WS_SERVICES_LIST, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        # DEVIATION (see docstring): the legacy path is REST + a per-request WS
        # bridge, NOT the shared pooled WS. A pooled-WS drop or a failed
        # (re)connect, both HomeAssistantConnectionError since #1947, must fall
        # back to REST rather than kill the tool.
        logger.warning(
            "%s connection error; falling back to REST legacy: %r",
            WS_SERVICES_LIST,
            exc,
        )
        return None
    result = raw.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("services"), list)
        or not isinstance(result.get("translations"), dict)
    ):
        logger.debug(
            "%s returned a malformed result (services/translations wrong shape); "
            "falling back to legacy",
            WS_SERVICES_LIST,
        )
        return None
    return result


async def _get_service_translations(
    client: Any, language: str, warnings: list[str] | None = None
) -> dict[str, Any]:
    """
    Get service translations from Home Assistant via WebSocket.

    Uses the frontend/get_translations command to retrieve
    human-readable service names and descriptions in Core's configured language.
    """
    try:
        response = await client.send_websocket_message(
            {
                "type": "frontend/get_translations",
                "language": language,
                "category": "services",
            }
        )

        if (
            isinstance(response, dict)
            and response.get("success")
            and response.get("result")
        ):
            result = response["result"]
            if isinstance(result, dict):
                resources: dict[str, Any] = result.get("resources", {})
                return resources
        return {}

    except (
        HomeAssistantConnectionError,
        HomeAssistantAPIError,
        HomeAssistantAuthError,
        TimeoutError,
        OSError,
    ) as e:
        logger.warning(f"Failed to get service translations: {e}")
        # An empty map is also what an instance with no translations returns,
        # so a caller that wants to tell the two apart passes ``warnings``
        # and reports that the catalog came back without descriptions (#1947).
        if warnings is not None:
            warnings.append(f"service descriptions unavailable: {e}")
        return {}


__all__ = [
    "register_services_tools",
]


async def _configured_language(client: Any) -> tuple[str, str | None]:
    """Core's configured language, plus a warning when it could not be read.

    ``frontend/get_translations`` requires a language. Core serves the configured
    one in ``/api/config``; falling back to English keeps the catalog usable when
    that read is unavailable, but the caller is told the text may be untranslated.
    """
    try:
        config = await client.get_config()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the configured language: %r", exc)
        return (
            "en",
            f"service descriptions may be untranslated: language unavailable: {exc}",
        )
    language = config.get("language") if isinstance(config, Mapping) else None
    if isinstance(language, str) and language:
        return language, None
    logger.warning("Home Assistant config carries no usable language: %r", config)
    return "en", "service descriptions may be untranslated: language unavailable"
