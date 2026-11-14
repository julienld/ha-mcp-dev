"""Detached logbook rows for one Core trace, without a transport."""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class TraceLogbook:
    """Logbook rows for one trace run."""

    entries: list[dict[str, Any]]
    transport: Literal["component", "rest"] | None
    warnings: list[str]
    total: int = 0
    truncated: bool = False
