"""Finite acceptance matrix and fail-closed upgrade evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from tests.native.catalog_contract import structural_schema


class UpgradeFailure(AssertionError):
    """A fixed failure category safe to retain in a public report."""


@dataclass(frozen=True)
class Profile:
    name: str
    route: str
    auth: str


PROFILES = (
    Profile("direct-secret", "direct", "none"),
    Profile("webhook-secret", "webhook", "none"),
    Profile("webhook-ha-bearer", "webhook", "ha-bearer"),
    Profile("webhook-ha-oauth", "webhook", "ha-oauth"),
    Profile("webhook-legacy-oauth", "webhook", "legacy-oauth"),
)
PHASES = ("main", "upgraded", "native", "restarted")
PROTOCOLS = ("2025-06-18", "2025-11-25", "2026-07-28")
_ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _schema_differences(
    name: str, old: dict[str, Any], new: dict[str, Any]
) -> list[dict[str, str]]:
    changes = []
    old_schema = structural_schema(old.get("inputSchema", {}))
    new_schema = structural_schema(new.get("inputSchema", {}))
    if set(new_schema.get("required", [])) - set(old_schema.get("required", [])):
        changes.append({"tool": name, "kind": "required_input_added"})
    changes.extend(
        {"tool": name, "kind": "input_changed", "parameter": parameter}
        for parameter, schema in old_schema.get("properties", {}).items()
        if new_schema.get("properties", {}).get(parameter) != schema
    )
    for field in old_schema.keys() | new_schema.keys():
        if field in {"properties", "required", "$defs", "definitions"}:
            continue
        if new_schema.get(field) != old_schema.get(field):
            changes.append({"tool": name, "kind": "schema_root_changed"})
    for group in ("$defs", "definitions"):
        changes.extend(
            {"tool": name, "kind": "definition_changed"}
            for definition, value in old_schema.get(group, {}).items()
            if new_schema.get(group, {}).get(definition) != value
        )
    return changes


def catalogue_differences(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, str]]:
    """Allow new tools/optional fields, report changes to existing callers."""
    changes = []
    for name, old in before.items():
        if name not in after:
            changes.append({"tool": name, "kind": "tool_removed"})
            continue
        new = after[name]
        changes.extend(_schema_differences(name, old, new))
        if structural_schema(old.get("outputSchema")) != structural_schema(
            new.get("outputSchema")
        ):
            changes.append({"tool": name, "kind": "output_schema_changed"})
        changes.extend(
            {"tool": name, "kind": "annotation_changed", "field": annotation}
            for annotation in _ANNOTATIONS
            if old.get("annotations", {}).get(annotation)
            != new.get("annotations", {}).get(annotation)
        )
    return changes


def validate_phase(
    baseline: dict[str, Any], current: dict[str, Any], connection_hash: str
) -> None:
    if (
        not re.fullmatch(r"[a-f0-9]{64}", connection_hash)
        or baseline.get("connection_hash") != connection_hash
        or current.get("connection_hash") != connection_hash
    ):
        raise UpgradeFailure("client_connection_changed")
    if (
        not isinstance(current.get("identity"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", current["identity"])
        or current["identity"] != baseline.get("identity")
    ):
        raise UpgradeFailure("persisted_connection_identity_changed")
    if current.get("grant_origin") != "main":
        raise UpgradeFailure("client_reauthorized_after_upgrade")
    if (
        current.get("connected") is not True
        or current.get("witness_preserved") is not True
    ):
        raise UpgradeFailure("existing_client_or_state_lost")
    if current.get("oauth") and current.get("old_grant_refreshed") is not True:
        raise UpgradeFailure("pre_upgrade_grant_cannot_refresh")


def report_passed(report: dict[str, Any], require_native: bool) -> bool:
    required = PHASES if require_native else PHASES[:2]
    profiles = report.get("profiles", [])

    def accepted(profile: dict[str, Any], phase: str) -> bool:
        observed = profile.get("phases", {}).get(phase, {})
        baseline = profile.get("phases", {}).get("main", {})
        try:
            validate_phase(baseline, observed, baseline.get("connection_hash", ""))
        except UpgradeFailure:
            return False
        return (
            observed.get("passed") is True
            and not observed.get("catalogue_changes")
            and observed.get("protocols") == dict.fromkeys(PROTOCOLS, True)
        )

    return (
        report.get("cleanup_complete") is True
        and report.get("sources_verified") is True
        and not report.get("failure")
        and len(profiles) == len(PROFILES)
        and {p.get("profile") for p in profiles} == {p.name for p in PROFILES}
        and all(
            not profile.get("cleanup_failed")
            and not profile.get("setup_failure_type")
            and all(accepted(profile, phase) for phase in required)
            for profile in profiles
        )
    )
