"""Keep ha-mcp's own integration on the one store repository that owns it.

Two repositories carry the ``ha_mcp_tools`` component: the main repository,
which the default catalog lists, and the distribution mirror earlier installs
came from. Both extract to ``custom_components/ha_mcp_tools``. The
Marketplace (Home Assistant 2026.11+) refuses to install a repository whose
integration another installed repository owns. HACS never checked, so a
download of the second repository on Home Assistant 2026.10 or older left both
records claiming the directory, and after the 2026.11 upgrade the Marketplace
refuses to update either (#2993). The server's own install guidance names the
main repository, so a download of either repository goes to the one that is
installed.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ..backends.legacy import legacy_errors
from ..client.rest_client import HomeAssistantCommandError, HomeAssistantCommandTimeout
from ..runtime.hacs_ownership import (
    CANDIDATE_REPO_FULL_NAMES,
    OWN_REPOSITORY_IDS,
    _own_name,
    route_installed_own_repository,
)
from .hacs_backend import StoreApi, is_owned_directory_refusal


async def installed_own_records(
    ws_client: Any, api: StoreApi
) -> list[dict[str, Any]] | None:
    """The store's records for ha-mcp's own repositories that are installed,
    or None when the store could not be asked."""
    try:
        response = await ws_client.send_command(api.command("list"))
    except HomeAssistantCommandError, HomeAssistantCommandTimeout:
        return None
    listed = response.get("result") if isinstance(response, dict) else None
    repos = [dict(r) for r in (listed or []) if isinstance(r, dict)]
    return [r for r in repos if _own_name(r) and r.get("installed")]


async def ownership_refusal_records(
    ws_client: Any, api: StoreApi, err: HomeAssistantCommandError
) -> list[str] | None:
    """For a store refusal, the installed own records' names, so the refusal
    can be explained; None for any other error, with no store call."""
    if not is_owned_directory_refusal(err):
        return None
    records = await installed_own_records(ws_client, api)
    return [str(r.get("full_name")) for r in records or []]


@partial(legacy_errors, classify=False)
async def route_own_repository_download(
    ws_client: Any, api: StoreApi, repository_id: str, version: str | None
) -> tuple[str, str | None, str | None]:
    """Read store records, then apply the shared installed-owner policy."""
    wanted = OWN_REPOSITORY_IDS.get(
        repository_id.strip().lower(), repository_id.strip().lower()
    )
    if wanted not in CANDIDATE_REPO_FULL_NAMES:
        return repository_id, version, None
    installed = await installed_own_records(ws_client, api)
    return route_installed_own_repository(
        repository_id, version, installed, is_marketplace=api.is_marketplace
    )
