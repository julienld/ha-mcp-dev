"""One repository-ownership routing policy for Native and remote store owners."""

from __future__ import annotations

import re
from typing import Any

from ha_mcp.errors import ErrorCode, create_error_response

from .errors import raise_failure

MAIN_REPOSITORY = "homeassistant-ai/ha-mcp"

MIRROR_REPOSITORY = "homeassistant-ai/ha-mcp-integration"

OWN_REPOSITORY_IDS = {"1056618941": MAIN_REPOSITORY, "1289599380": MIRROR_REPOSITORY}

_MAIN_DEV_REF = re.compile(r"^(v?\d+\.\d+\.\d+)\.dev(\d+)$")

_MIRROR_DEV_REF = re.compile(r"^(v?\d+\.\d+\.\d+)-dev\.(\d+)$")

_RELEASE_REF = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")

_SHARED_TAGS_SINCE = (9, 0, 0)


CANDIDATE_REPO_FULL_NAMES = frozenset({MAIN_REPOSITORY, MIRROR_REPOSITORY})


def _tagged_alike(version: str) -> bool:
    match = _RELEASE_REF.match(version)
    if match is None:
        return False
    return tuple(int(p) for p in match.groups()) >= _SHARED_TAGS_SINCE


def translate_version(version: str | None, target: str) -> str | None:
    """The same release named the way ``target`` tags it."""
    if not version:
        return version
    if target.lower() == MIRROR_REPOSITORY and (match := _MAIN_DEV_REF.match(version)):
        return f"{match[1]}-dev.{match[2]}"
    if target.lower() == MAIN_REPOSITORY and (match := _MIRROR_DEV_REF.match(version)):
        return f"{match[1]}.dev{match[2]}"
    return version


def _own_name(repo: dict[str, Any]) -> str | None:
    full_name = (repo.get("full_name") or "").lower()
    if full_name in {n.lower() for n in CANDIDATE_REPO_FULL_NAMES}:
        return full_name
    return None


def route_installed_own_repository(
    repository_id: str,
    version: str | None,
    installed: list[dict[str, Any]] | None,
    *,
    is_marketplace: bool,
) -> tuple[str, str | None, str | None]:
    """Route to the installed owner without performing transport or owner calls."""
    wanted = repository_id.strip().lower()
    wanted = OWN_REPOSITORY_IDS.get(wanted, wanted)
    if wanted not in {n.lower() for n in CANDIDATE_REPO_FULL_NAMES}:
        return repository_id, version, None

    if installed is None:
        # The download itself reports the store's trouble, with its own context
        return repository_id, version, None
    if len(installed) > 1:
        if is_marketplace:
            # The Marketplace refuses this download itself; raise_store_error
            # explains the refusal with the way out.
            return repository_id, version, None
        names = " and ".join(str(r.get("full_name")) for r in installed)
        # HACS never checked ownership, so the download still works there and
        # is the way to bring in the release whose repair keeps one listing.
        note = (
            f"{names} are both installed and both claim "
            "custom_components/ha_mcp_tools. HACS still updates either, but the "
            "Marketplace in Home Assistant 2026.11 will refuse to. After this "
            "download restart Home Assistant and run the repair under Settings > "
            f"System > Repairs, which keeps {MAIN_REPOSITORY}. If no repair "
            "appears, the installed release predates it: update to a current "
            "release or follow the manual route in the FAQ."
        )
        return repository_id, version, note
    if not installed or _own_name(installed[0]) == wanted:
        return repository_id, version, None
    owner = str(installed[0].get("full_name"))
    if version and not _tagged_alike(version):
        raise_failure(
            create_error_response(
                ErrorCode.VALIDATION_INVALID_PARAMETER,
                f"{owner} owns custom_components/ha_mcp_tools, and releases "
                f"before {'.'.join(map(str, _SHARED_TAGS_SINCE))} are tagged "
                f"differently there, so {version} cannot be mapped to it.",
                suggestions=[
                    "Pick a version from the installed repository: "
                    'ha_get_hacs_info(action="info", '
                    f'repository_id="{owner}", include_releases=True), then '
                    f'ha_manage_hacs(action="download", repository_id="{owner}", '
                    'version="<one of its tags>").',
                    "Or omit version to install its latest release.",
                ],
                context={"repository_id": repository_id, "version": version},
            ),
            status="not_started",
        )
    target_version = translate_version(version, owner)
    note = (
        f"{repository_id} was rerouted to {owner}, which already owns "
        "custom_components/ha_mcp_tools; HA-MCP stays on the one listing it "
        "was installed from."
    )
    if target_version != version:
        note += f" The version was renamed from {version} to {target_version}."
    return owner, target_version, note
