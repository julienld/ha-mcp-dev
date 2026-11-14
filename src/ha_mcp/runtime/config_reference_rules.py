"""Project Core reference verdicts without copying its extraction or target rules."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

ConfigKind = Literal["automation", "script", "scene"]
RefKind = Literal["service", "entity", "device", "area", "floor", "label"]


class ValidationWarning(TypedDict):
    """One warning in the tool response.

    A missing reference has no ``path``: Core's helpers collect references as
    sets. A target Core does not offer carries its ``path``, the item it is a
    target of (``target_of``) and what Core does offer for it (``offered``).
    """

    kind: RefKind
    value: str
    reason: str
    path: NotRequired[str]
    target_of: NotRequired[str]
    offered: NotRequired[list[str]]


class ValidationMeta(TypedDict):
    """Core's warnings, or why the references went unchecked."""

    warnings: list[ValidationWarning]
    references_unchecked: NotRequired[str]


def _warnings(answer: dict[str, Any]) -> list[ValidationWarning]:
    warnings: list[ValidationWarning] = [
        {
            "kind": missing["kind"],
            "value": missing["value"],
            "reason": f"Home Assistant has no {missing['kind']} {missing['value']}",
        }
        for missing in answer["missing"]
    ]
    warnings.extend(
        {
            "kind": "entity",
            "value": mismatch["entity_id"],
            "path": mismatch["path"],
            "target_of": mismatch["name"],
            "offered": mismatch["offered"],
            "reason": (
                f"Home Assistant does not offer {mismatch['entity_id']} as a "
                f"target of {mismatch['name']}; see offered for what it does offer"
            ),
        }
        for mismatch in answer["mismatches"]
    )
    return warnings


def reference_validation_meta(answer: dict[str, Any]) -> ValidationMeta:
    """Keep Core's warnings or the explicit reason no references were checked."""
    if answer["status"] != "ok":
        return {
            "warnings": [],
            "references_unchecked": answer.get("error")
            or f"references were not checked: the check answered {answer['status']}",
        }
    return {"warnings": _warnings(answer)}
