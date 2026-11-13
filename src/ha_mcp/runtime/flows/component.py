"""Core flow metadata behind the same finite ports as flow execution."""

from typing import Any

from .session import FlowSession


async def component_serves(client: FlowSession, capability: str) -> bool:
    info = await client.backend.execute("component.capabilities", {}, client.context)
    return capability in info["capabilities"]


async def flow_record(
    client: FlowSession, manager: str, flow_id: str
) -> dict[str, Any] | None:
    return await client.backend.execute(
        "config.flow.record", {"manager": manager, "flow_id": flow_id}, client.context
    )


async def flow_outline(
    client: FlowSession, domain: str, flow: str
) -> list[dict[str, Any]] | None:
    result = await client.backend.execute(
        "config.flow.outline", {"domain": domain, "flow": flow}, client.context
    )
    steps = result.get("steps") if result and result.get("supported") else None
    return (
        [step for step in steps if isinstance(step, dict)]
        if isinstance(steps, list)
        else None
    )


def steps_after(
    steps: list[dict[str, Any]], step_id: str
) -> list[tuple[dict[str, Any], bool]] | None:
    """The steps Core may show after ``step_id``, each with whether it always
    follows. Where Core picks the next step from the answers, every step not
    yet passed is listed as a candidate: the declaration does not say which
    of them the callback can return. A step Core passes without
    showing a form is followed, not listed. ``None`` when the outline does not
    hold ``step_id`` (a reconfigure step is not part of it).
    """
    by_id = {step.get("step_id"): step for step in steps}
    current = by_id.get(step_id)
    if current is None:
        return None
    later: list[tuple[dict[str, Any], bool]] = []
    seen = {step_id}
    while True:
        if current.get("next_from_answers"):
            later.extend(
                (step, False)
                for name, step in by_id.items()
                if name not in seen and _shown(step)
            )
            break
        current = by_id.get(current.get("next_step"))
        if current is None or current["step_id"] in seen:
            break
        seen.add(current["step_id"])
        if _shown(current):
            later.append((current, True))
    return later


def _shown(step: dict[str, Any]) -> bool:
    """Whether Core shows something at ``step``: a form step declared without
    a schema is passed straight through."""
    return (
        step.get("type") != "form"
        or step.get("data_schema") is not None
        or bool(step.get("schema_from_answers"))
    )
