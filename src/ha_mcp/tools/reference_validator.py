"""References checked by Core through the component, with no copied-rule fallback."""

from __future__ import annotations

from typing import Any

from ..runtime.config_reference_rules import (
    ConfigKind,
    ValidationMeta,
    reference_validation_meta,
)
from ..runtime.config_reference_rules import _warnings as _warnings
from .component_config_reads import fetch_config_references_via_component


async def validate_config_references(
    client: Any, config: dict[str, Any], kind: ConfigKind
) -> ValidationMeta:
    """Report Core's verdict, or why the references went unchecked."""
    answer = await fetch_config_references_via_component(client, kind, config)
    return reference_validation_meta(answer)
