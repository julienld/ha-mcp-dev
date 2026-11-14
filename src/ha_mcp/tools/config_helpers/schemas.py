"""Legacy bindings over the shared Core helper schema contract."""

from typing import Any

from ha_mcp.runtime import helper_schema as _shared

from ..config_write_helpers import attach_skill_content

SIMPLE_HELPER_TYPES = _shared.SIMPLE_HELPER_TYPES
StorageHelperType = _shared.StorageHelperType
_CORE_HELPER_SCHEMAS = _shared._CORE_HELPER_SCHEMAS
_HELPER_SKILL_FILES = _shared._HELPER_SKILL_FILES
SIMPLE_CONFIG_KEYS_DESCRIPTION = _shared.SIMPLE_CONFIG_KEYS_DESCRIPTION
HelperResponse = _shared.HelperResponse
_simple_helper_error_context = _shared._simple_helper_error_context

__all__ = [
    "HelperResponse",
    "SIMPLE_HELPER_TYPES",
    "StorageHelperType",
    "_CORE_HELPER_SCHEMAS",
    "_HELPER_SKILL_FILES",
    "SIMPLE_CONFIG_KEYS_DESCRIPTION",
    "_attach_helper_skill",
    "_simple_helper_error_context",
]


def _attach_helper_skill(response: dict[str, Any], MandatoryBPS: bool) -> None:
    """In-place attach skill_content to a helper response when applicable.

    Helper tool has no best-practice checker integration, so
    ``referenced_files`` is always None — embedding is driven purely by
    the ``MandatoryBPS`` flag. Delegates to the shared
    :func:`attach_skill_content` so the missing-vendor-warning path is
    consistent across every write tool.
    """
    attach_skill_content(
        response,
        MandatoryBPS=MandatoryBPS,
        canonical_files=_HELPER_SKILL_FILES,
        referenced_files=None,
    )
