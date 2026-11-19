"""The HACS public contracts shared by direct owners and the remote adapter."""

import logging
from typing import Annotated, Any, Literal, Protocol

from pydantic import Field

from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.tool_api import ToolFailure

from .errors import raise_classified, raise_failure
from .hacs_values import CATEGORY_HELP, _reject_foreign_params
from .validation import validate_identifier_not_empty

logger = logging.getLogger(__name__)


class HacsService(Protocol):
    async def _hacs_accept_warning(self, confirm: bool | None) -> dict[str, Any]: ...
    async def _hacs_search(
        self,
        query: str,
        category: str | None,
        installed_only: bool,
        max_results: int,
        offset: int,
        ctx: Any,
    ) -> dict[str, Any]: ...
    async def _hacs_info(
        self, repository_id: str, include_releases: bool = False
    ) -> dict[str, Any]: ...
    async def _hacs_download(
        self,
        repository_id: str | None,
        version: str | None,
        confirm_replace_built_in: bool = False,
    ) -> dict[str, Any]: ...
    async def _hacs_remove(self, repository_id: str | None) -> dict[str, Any]: ...
    async def _hacs_update_information(
        self, repository_id: str | None
    ) -> dict[str, Any]: ...
    async def _hacs_add_repository(
        self, repository: str, category: str
    ) -> dict[str, Any]: ...


class HacsFacade:
    def __init__(self, hacs: HacsService) -> None:
        self.hacs = hacs

    async def ha_get_hacs_info(
        self,
        action: Annotated[
            Literal["search", "info"],
            Field(description="'search' the store, or 'info' for one repository"),
        ],
        query: Annotated[
            str, Field(description="Search keyword (action='search')")
        ] = "",
        category: Annotated[
            str | None,
            Field(description="Filter by category (action='search')"),
        ] = None,
        installed_only: Annotated[
            bool,
            Field(description="Only return installed repositories (action='search')"),
        ] = False,
        max_results: Annotated[
            int,
            Field(
                ge=1,
                le=100,
                description="Maximum number of results (action='search')",
            ),
        ] = 10,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description="Results to skip for pagination (action='search')",
            ),
        ] = 0,
        repository_id: Annotated[
            str | None,
            Field(description="Numeric HACS ID or 'owner/repo' path (action='info')"),
        ] = None,
        include_releases: Annotated[
            bool,
            Field(
                description="Include release and release-note reads from the store (action=info)"
            ),
        ] = False,
        ctx: Any = None,
    ) -> dict[str, Any]:
        """Get HACS or Home Assistant Marketplace data — search the store or read repository details.

        Use ``action="search"`` to search/browse/list store repositories, or
        ``action="info"`` for one repository's full details (README, versions, GitHub
        stats). This tool is read-only; to install or add repositories use
        ``ha_manage_hacs``, and for non-HACS entities/config use the domain-specific tools.

        **DASHBOARD TIP:** ``action="search", installed_only=True, category="lovelace"``
        discovers installed custom cards to wire into ``ha_config_set_dashboard()``.

        **Examples:**
        - Search the store: ha_get_hacs_info(action="search", query="mushroom", category="lovelace")
        - List installed: ha_get_hacs_info(action="search", installed_only=True)
        - Repository details: ha_get_hacs_info(action="info", repository_id="441028036")

        **Caveats:** search reads the loaded catalog. Info follows the store's
        own metadata policy: the first read can fetch GitHub details, clear its
        new flag and save metadata; it does not install repository code.
        include_releases=True also fetches releases and release notes; failures
        become warnings alongside the repository details. Use
        ha_manage_hacs(action="update_information") for an explicit later refresh.
        Marketplace no longer supports appdaemon or python_script repositories.
        """
        if action == "search":
            return await self.hacs._hacs_search(
                query, category, installed_only, max_results, offset, ctx
            )

        # action == "info"
        repository_id = validate_identifier_not_empty(
            repository_id,
            "repository_id",
            message="repository_id is required for action='info'",
            suggestions=[
                "Pass repository_id (numeric HACS ID or 'owner/repo')",
                "Use action='search' to find the repository first",
            ],
        )
        if include_releases:
            return await self.hacs._hacs_info(repository_id, include_releases=True)
        return await self.hacs._hacs_info(repository_id)

    async def ha_manage_hacs(
        self,
        action: Annotated[
            Literal[
                "download",
                "add_repository",
                "remove",
                "update_information",
                "accept_warning",
            ],
            Field(
                description=(
                    "'download' to install/update, 'add_repository' to register "
                    "a custom repo, 'remove' to uninstall a downloaded repo, "
                    "'update_information' to refresh a repository's release data "
                    "from GitHub, or 'accept_warning' to accept the "
                    "Marketplace's first-run warning for the user this server "
                    "connects as"
                )
            ),
        ],
        repository_id: Annotated[
            str | None,
            Field(
                description=(
                    "Numeric HACS ID or 'owner/repo' path "
                    "(action='download' / 'remove' / 'update_information')"
                )
            ),
        ] = None,
        version: Annotated[
            str | None,
            Field(description="Specific version to install (action='download')"),
        ] = None,
        repository: Annotated[
            str | None,
            Field(
                description="GitHub repo 'owner/repo' to add (action='add_repository')"
            ),
        ] = None,
        category: Annotated[
            str | None,
            Field(
                description=f"Repository category (action='add_repository'). {CATEGORY_HELP}"
            ),
        ] = None,
        confirm_replace_built_in: Annotated[
            bool | None,
            Field(
                description=(
                    "Marketplace only (action='download'): install a repository "
                    "that replaces the built-in integration of the same domain. "
                    "Set it only after the user agrees."
                )
            ),
        ] = None,
        confirm: Annotated[
            bool | None,
            Field(
                description=(
                    "action='accept_warning': True once the user has said they "
                    "read the Marketplace's first-run warning and accept it"
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Manage HACS (Home Assistant Community Store) — install/update, remove, add custom repositories, or refresh repository information.

        On Home Assistant 2026.11+ HACS is the built-in Marketplace; the tool
        uses whichever the instance has. This tool performs writes; to search the
        store or read repository details use ``ha_get_hacs_info``. Use
        ``action="update_information"`` to run the HACS UI's "Update information"
        action ("Refresh information" in the Marketplace) — a forced re-fetch of
        one repository's release data from GitHub, so a pending update becomes
        visible to the store and its update entity immediately.

        **Examples:**
        - Install latest: ha_manage_hacs(action="download", repository_id="441028036")
        - Install a version: ha_manage_hacs(action="download", repository_id="piitaya/lovelace-mushroom", version="v4.0.0")
        - Remove: ha_manage_hacs(action="remove", repository_id="owner/repo")
        - Add a custom repo: ha_manage_hacs(action="add_repository", repository="owner/repo", category="lovelace")
        - Refresh release data: ha_manage_hacs(action="update_information", repository_id="owner/repo")
        - Accept the Marketplace warning: ha_manage_hacs(action="accept_warning", confirm=True)

        **Caveats:** Installing an integration usually needs a Home Assistant restart to
        activate; new Lovelace cards need a browser cache clear. ``add_repository`` requires ``owner/repo``
        format plus a matching ``category``. Removing an integration deletes its files but
        the loaded module persists until the next Home Assistant restart — delete its config
        entries first (``ha_remove_helpers_integrations``). HACS refreshes custom
        repositories on its own only about every 48 hours (the Marketplace only with a
        connected GitHub account), so ``update_information`` is the way to surface a
        just-published release. The Marketplace refuses installs until the user this server
        connects as has accepted its first-run warning; Home Assistant keeps that per user,
        so the user's own acceptance in the UI does not cover this server. Ask the user
        whether they have read it (Settings > Marketplace) and accept it before
        ``accept_warning``. Adding a repository needs a GitHub account the user connects in
        the Marketplace panel.
        """
        try:
            # Reject parameters that don't belong to the chosen action rather
            # than silently discarding them — ha_manage_hacs(action="remove",
            # version="v4.0.0") plausibly means "uninstall this version",
            # which remove cannot honor, and dropping it would remove the
            # whole repository while reporting plain success.
            _reject_foreign_params(
                action,
                download={
                    "repository": repository,
                    "category": category,
                    "confirm": confirm,
                },
                remove={
                    "version": version,
                    "repository": repository,
                    "category": category,
                    "confirm_replace_built_in": confirm_replace_built_in,
                    "confirm": confirm,
                },
                add_repository={
                    "repository_id": repository_id,
                    "version": version,
                    "confirm_replace_built_in": confirm_replace_built_in,
                    "confirm": confirm,
                },
                update_information={
                    "version": version,
                    "repository": repository,
                    "category": category,
                    "confirm_replace_built_in": confirm_replace_built_in,
                    "confirm": confirm,
                },
                accept_warning={
                    "repository_id": repository_id,
                    "version": version,
                    "repository": repository,
                    "category": category,
                    "confirm_replace_built_in": confirm_replace_built_in,
                },
            )

            if action == "download":
                return await self.hacs._hacs_download(
                    repository_id, version, bool(confirm_replace_built_in)
                )

            if action == "remove":
                return await self.hacs._hacs_remove(repository_id)

            if action == "update_information":
                return await self.hacs._hacs_update_information(repository_id)

            if action == "accept_warning":
                if confirm is not True:
                    raise_failure(
                        create_error_response(
                            ErrorCode.VALIDATION_INVALID_PARAMETER,
                            "action='accept_warning' needs confirm=True after the user read and accepted the Marketplace warning.",
                        )
                    )
                return await self.hacs._hacs_accept_warning(confirm)

            # action == "add_repository"
            repository = validate_identifier_not_empty(
                repository,
                "repository",
                suggestions=["Pass repository in 'owner/repo' format"],
            )
            category = validate_identifier_not_empty(
                category,
                "category",
                suggestions=[
                    "Pass one of the categories in ha_get_hacs_info(action='search')'s store.categories"
                ],
            )
            return await self.hacs._hacs_add_repository(repository, category)

        except ToolFailure:
            raise
        except Exception as e:  # noqa: BLE001
            raise_classified(
                e,
                context={"tool": "ha_manage_hacs", "action": action},
                suggestions=[
                    "Verify HACS (the Marketplace on Home Assistant 2026.11+) is available",
                    "For action='download', 'remove', or 'update_information', pass a valid repository_id (use ha_get_hacs_info(action='search') to find it)",
                    "For action='add_repository', use 'owner/repo' format and a matching category",
                ],
            )
            return None  # unreachable: exception_to_structured_error raises
