"""Registry recovery uses the saved Core identity and a compared before-image."""

from typing import Any

from ha_mcp.tool_api import Backend, CallContext, ToolFailure, UnsupportedOperation

from .registry_recovery_values import note_registry_identity, registry_fields_match
from .snapshot_payloads import InvalidBackupSnapshotError, _strip_readonly


def registry_target(
    domain: str, entity_id: str, config: Any
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if not isinstance(config, dict):
        raise InvalidBackupSnapshotError("Registry snapshot must contain an object")
    if domain == "category":
        scope, category_id = config.get("scope"), config.get("category_id")
        if (
            not isinstance(scope, str)
            or not isinstance(category_id, str)
            or not category_id
            or entity_id != f"{scope}:{category_id}"
        ):
            raise InvalidBackupSnapshotError(
                "Category snapshot does not match its scope and identity"
            )
        return (
            "category",
            {"scope": scope, "category_id": category_id},
            {"scope": scope},
        )
    if domain == "area_or_floor":
        kind = config.get("kind")
        key = f"{kind}_id"
        identifier = config.get(key)
        if (
            kind not in {"area", "floor"}
            or not isinstance(identifier, str)
            or not identifier
            or entity_id != f"{kind}:{identifier}"
        ):
            raise InvalidBackupSnapshotError(
                "Location snapshot does not match its kind and identity"
            )
        return kind, {key: identifier}, {"kind": kind}
    raise UnsupportedOperation(f"snapshots.{domain}.read")


async def current_registry(
    backend: Backend, actor: CallContext, domain: str, entity_id: str, config: Any
) -> dict[str, Any] | None:
    kind, target, metadata = registry_target(domain, entity_id, config)
    row = await backend.execute(f"registry.{kind}.read", target, actor)
    return {**metadata, **row} if row is not None else None


async def restore_registry(
    backend: Backend,
    actor: CallContext,
    domain: str,
    entity_id: str,
    config: Any,
    before: dict[str, Any] | None,
) -> Any:
    kind, target, metadata = registry_target(domain, entity_id, config)
    if before is None:
        id_key = f"{kind}_id"
        query: dict[str, Any] = {"registries": [kind]}
        if kind == "category":
            query["category_scopes"] = [target["scope"]]
        snapshot = await backend.execute("registries.snapshot", query, actor)
        rows = (
            snapshot["categories"][target["scope"]]
            if kind == "category"
            else snapshot[f"{kind}s"]
        )
        if any(row.get(id_key) == target[id_key] for row in rows):
            raise ToolFailure(
                "CONFIG_CONFLICT",
                "The removed registry item reappeared before restoration",
                status="not_started",
            )
        payload = _strip_readonly(config, *metadata, id_key)
        for row in rows:
            if registry_fields_match(row, payload):
                return note_registry_identity(row, id_key, target[id_key])
        data = {key: value for key, value in payload.items() if value is not None}
        if kind == "category":
            data["scope"] = target["scope"]
        result = await backend.execute(
            f"registry.{kind}.create",
            {"data": data, "expected_item": None, "expected_absent": target},
            actor,
        )
        if not result.get("success"):
            raise ToolFailure(
                "RESTORE_FAILED",
                "Core rejected registry recreation",
                status="not_started",
            )
        return note_registry_identity(result["result"], id_key, target[id_key])
    # An area's floor_id is writable affiliation, not the area's own identity.
    result = await backend.execute(
        f"registry.{kind}.update",
        {
            "data": {**_strip_readonly(config, *metadata), **target},
            "expected_item": {
                key: value for key, value in before.items() if key not in metadata
            },
        },
        actor,
    )
    if not result.get("success"):
        raise ToolFailure(
            "RESTORE_FAILED", "Core rejected registry restoration", status="not_started"
        )
    return result["result"]


async def registry_comparison(
    backend: Backend,
    actor: CallContext,
    domain: str,
    entity_id: str,
    config: dict[str, Any],
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compare a recreated item under Core's actual id, preserving timestamp history."""
    if current is None:
        metadata: dict[str, Any]
        if domain == "label":
            kind, metadata = "label", {}
        else:
            kind, _target, metadata = registry_target(domain, entity_id, config)
        arguments: dict[str, Any] = {"registries": [kind]}
        if kind == "category":
            arguments["category_scopes"] = [metadata["scope"]]
        snapshot = await backend.execute("registries.snapshot", arguments, actor)
        rows = (
            snapshot["categories"][metadata["scope"]]
            if kind == "category"
            else snapshot[f"{kind}s"]
        )
        row = next((row for row in rows if row.get("name") == config.get("name")), None)
        current = {**metadata, **row} if row is not None else None
    if current is not None:
        keep = {
            key: value
            for key, value in config.items()
            if key in {"created_at", "modified_at"}
        }
        current = {**current, **keep}
    return current
