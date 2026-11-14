"""Core-authoritative helper collision checks shared by both backend families."""

from typing import Any

from ha_mcp.errors import ErrorCode, create_error_response

from .component_messages import COMPONENT_INSTALL_HINT
from .errors import raise_failure as raise_tool_error
from .helper_schema import SIMPLE_HELPER_TYPES, _simple_helper_error_context

_NEAR_DUPLICATES_UNCHECKED = (
    "Only a helper with exactly this name or id was looked for as a duplicate. "
    "A name that differs only in case or punctuation is found with the "
    "ha_mcp_tools component, and without it Home Assistant creates such a "
    "helper numbered (..._2). " + COMPONENT_INSTALL_HINT
)


async def _check_name_collision(
    client: Any,
    helper_type: str,
    name: str | None,
) -> str | None:
    """Reject create requests whose name collides with an existing helper (Bug 12).

    HA's create endpoints auto-suffix duplicate names with `_2` / `_3` etc., so
    a caller asking to "create" a helper that already exists silently gets a
    duplicate entity instead of updating the original. Detect and reject before
    we send the create message, pointing the caller at the existing helper_id.

    Which names collide is Core's rule (its ``slugify``), so the component
    answers with Core's own function. Without the component only a helper
    with exactly this name or id is found, and Core numbers a near-duplicate:
    the returned warning says so, for the caller's response.

    Empty / missing / whitespace-only `name` is left to Core's name check.
    """
    if not name or not name.strip():
        return None
    slug = None
    not_stored = False
    unchecked: str | None = _NEAR_DUPLICATES_UNCHECKED
    named = await client.backend.execute(
        "helpers.named", {"helper_type": helper_type, "name": name}, client.context
    )
    if named is not None and isinstance(named.get("ids"), list):
        unchecked = (
            None if named.get("normalized", True) else _NEAR_DUPLICATES_UNCHECKED
        )
        existing_id = named["ids"][0] if named["ids"] else None
        slug = named.get("slug")
        not_stored = existing_id in (named.get("not_stored") or [])
    else:
        raise_tool_error(
            create_error_response(
                ErrorCode.SERVICE_CALL_FAILED, "Core returned no helper name lookup"
            )
        )

    if existing_id is None:
        return unchecked

    different_name = "To create a separate helper, pick a different name" + (
        f" (Home Assistant turns this one into {slug!r})." if slug else "."
    )
    raise_tool_error(
        create_error_response(
            ErrorCode.VALIDATION_INVALID_PARAMETER,
            f"A {helper_type} helper named {name!r} already exists "
            f"(id: {existing_id!r}). "
            + (
                "It is not a stored helper (it is defined in YAML or by Home "
                "Assistant itself), so this tool cannot update it; use a "
                "different name to create a new helper."
                if not_stored
                else f"Pass helper_id={existing_id!r} to update it, "
                "or use a different name to create a new helper."
            ),
            context=_simple_helper_error_context(
                helper_type,
                name=name,
                existing_helper_id=existing_id,
            )
            if helper_type in SIMPLE_HELPER_TYPES
            else {
                "helper_type": helper_type,
                "name": name,
                "existing_helper_id": existing_id,
            },
            suggestions=[different_name]
            if not_stored
            else [
                f"To update the existing helper, pass helper_id={existing_id!r} "
                "(and omit `name`).",
                different_name,
            ],
        )
    )
    # CodeQL (py/mixed-returns) reads raise_tool_error as returning.
    raise AssertionError("unreachable: raise_tool_error always raises")
