"""Error reporting for config-entry flow walks.

Turns Home Assistant's answers to a flow submit (a 400/422 body, a form
with ``errors``, an ``abort`` step) into structured ``ToolError``s, and holds
the reconfigure outcome vocabulary those errors carry.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

from ha_mcp.errors import ErrorCode, HomeAssistantAPIError, create_error_response
from ha_mcp.runtime.errors import raise_failure as raise_tool_error
from ha_mcp.runtime.flow_translations import (
    fetch_flow_strings,
    flow_text,
    strings_unread_warning,
)
from ha_mcp.runtime.flows.introspect import fetch_helper_flow_info
from ha_mcp.runtime.flows.settings import redaction_enabled
from ha_mcp.runtime.redaction import redact_flow_schema

from .settings import no_answer_errors

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlowRef:
    """Where a flow's strings live: ``component.<domain>.<path>``.

    ``path`` is ``config`` (config and reconfigure flows), ``options`` or
    ``config_subentries.<type>``. An options or subentry flow can name its
    entry's ``entry_id`` and leave ``domain`` ``None``: the error, abort and
    progress texts then read the domain from the entry, while
    ``describe_form`` shows no help text.
    """

    domain: str | None
    path: str
    entry_id: str | None = None

    def __post_init__(self) -> None:
        if self.path.split(".")[0] not in {"config", "options", "config_subentries"}:
            raise ValueError(f"Not a config entry flow path: {self.path!r}")


async def _flow_texts(
    client: Any,
    flow: FlowRef | None,
    step: dict[str, Any],
    kind: str,
    keys: dict[str, Any],
) -> dict[str, Any]:
    """Core's text for each ``<path>.<kind>.<key>``, as the frontend looks it up.

    ``keys`` maps an output key (a field name, or ``reason_text`` /
    ``progress_action_text``) to its translation key; a key Core ships no
    string for is left out, so the caller keeps the raw key. A failed strings
    read, or a failed read of the entry's domain, gives ``warnings`` instead.
    """
    if flow is None or not keys:
        return {}
    domain, path = flow.domain, flow.path
    if isinstance(step.get("translation_domain"), str):
        # The reason belongs to another integration. A subentry abort reads
        # it under that integration's config strings, as the frontend's dev
        # branch does; the release Core 2026.8.0 pins reads
        # config_subentries.<type>.abort instead.
        domain = step["translation_domain"]
        if kind == "abort" and path.startswith("config_subentries."):
            path = "config"
    elif domain is None and flow.entry_id:
        try:
            domain = (await client.get_config_entry(flow.entry_id)).get("domain")
        except Exception:  # the text is best effort
            logger.warning(
                "domain of %s for flow text failed", flow.entry_id, exc_info=True
            )
            return {
                "warnings": [
                    f"The domain of config entry {flow.entry_id} could not be "
                    "read, so Home Assistant's texts for this flow step are "
                    "missing"
                ]
            }
    if not isinstance(domain, str):
        return {}
    strings = await fetch_flow_strings(client, domain, path.split(".")[0])
    if strings is None:
        return {"warnings": [strings_unread_warning(domain)]}
    placeholders = step.get("description_placeholders")
    texts = {
        name: flow_text(strings, domain, f"{path}.{kind}.{key}", placeholders)
        for name, key in keys.items()
        if isinstance(key, str)
    }
    return {name: text for name, text in texts.items() if text}


class ReconfigureStatus(StrEnum):
    """Outcome vocabulary for the ``ha_set_integration`` reconfigure mode.

    Ordered by how far the request got. Everything from ``APPLIED_*`` onward
    means Home Assistant committed the change, or may have, so a caller must
    not blindly retry those. Every flow walk also uses
    ``APPLIED_BUT_UNVERIFIED`` for a submit or poll whose answer was lost.
    """

    #: The flow was aborted before any value reached Home Assistant.
    FLOW_ABORTED_BEFORE_APPLY = "flow_aborted_before_apply"
    #: Home Assistant rejected the change; nothing was committed.
    APPLY_FAILED = "apply_failed"
    #: Committed, but the flow never consumed every supplied value.
    APPLIED_BUT_INCOMPLETE = "applied_but_incomplete"
    #: Committed, and the entry reloaded cleanly.
    APPLIED_AND_VERIFIED = "applied_and_verified"
    #: Maybe committed: the answer was lost.
    APPLIED_BUT_UNVERIFIED = "applied_but_unverified"


def _parse_flow_api_error(
    api_error: HomeAssistantAPIError,
) -> dict[str, Any]:
    """Extract structured field-level info from an HA flow 4xx response.

    Home Assistant returns voluptuous validation failures during flow
    submission as either:

    - ``{"message": "User input malformed: extra keys not allowed @ data['name']"}``
      (raised before form validation, e.g. unknown field in payload)
    - ``{"errors": {"base": "..."}, "description_placeholders": {...}}``
      (per-field errors after voluptuous validation succeeds)
    - Free-form text (when the body isn't JSON).

    Returns a dict with at least:
      - ``message``: the most informative human-readable string we found.
      - ``field_errors``: dict of field-name -> error code/message, when
        the body contained an ``errors`` map. Empty dict otherwise.
      - ``raw``: the response_data dict (or ``None``) for diagnostics.
    """
    body = api_error.response_data or {}
    field_errors: dict[str, Any] = {}
    message_parts: list[str] = []

    if isinstance(body, dict):
        errors_field = body.get("errors")
        if isinstance(errors_field, dict):
            field_errors = {
                key: val for key, val in errors_field.items() if isinstance(key, str)
            }

        # HA's stock 400 carries a `message` key with the voluptuous detail.
        msg = body.get("message")
        if isinstance(msg, str) and msg.strip():
            message_parts.append(msg.strip())

        # description_placeholders sometimes carry the human-readable error.
        placeholders = body.get("description_placeholders")
        if isinstance(placeholders, dict):
            for key, val in placeholders.items():
                if isinstance(val, str) and val.strip():
                    message_parts.append(f"{key}: {val.strip()}")

    if not message_parts:
        # Fall back to the wrapper exception message ("API error: 400 - ...").
        message_parts.append(str(api_error))

    return {
        "message": " | ".join(dict.fromkeys(message_parts)),  # de-dupe, preserve order
        "field_errors": field_errors,
        "raw": body if isinstance(body, dict) else None,
    }


def _build_flow_error_context(
    flow_id: str,
    status_code: int,
    helper_type: str | None,
    menu_choice: str | None,
    current_step: dict[str, Any] | None,
    submitted: dict[str, Any] | None,
    parsed_raw: dict[str, Any] | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {"flow_id": flow_id, "status_code": status_code}
    if helper_type:
        context["helper_type"] = helper_type
    if menu_choice:
        context["menu_choice"] = menu_choice
    if current_step is not None:
        context["step_id"] = current_step.get("step_id")
    if submitted is not None:
        context["submitted_keys"] = sorted(submitted.keys())
    if parsed_raw is not None:
        context["response_body"] = parsed_raw
    return context


def _flow_error_subject(
    helper_type: str | None, *, is_reconfigure: bool, validation: bool
) -> str:
    """What a rejected flow submit's message names; ``helper_type`` carries
    the integration domain under ``is_reconfigure``."""
    if is_reconfigure and helper_type:
        subject = f"{helper_type} reconfigure"
    elif is_reconfigure:
        subject = "Reconfigure" if validation else "reconfigure"
    else:
        subject = "Helper" if validation else helper_type or "flow"
    return f"{subject} validation" if validation else subject


async def _raise_flow_api_error(
    api_error: HomeAssistantAPIError,
    *,
    client: Any,
    flow_id: str,
    helper_type: str | None,
    menu_choice: str | None,
    current_step: dict[str, Any] | None,
    submitted: dict[str, Any] | None,
    is_reconfigure: bool = False,
    flow_stays_open: bool = False,
) -> NoReturn:
    """Translate an HA 4xx during a flow submit into a structured ToolError.

    For 400/422 responses, parses ``response_data`` for field-level info
    via ``_parse_flow_api_error``. Attaches a ``data_schema`` whenever one is
    found, next to ``field_errors`` or in place of them, so the caller sees
    what Home Assistant accepts.

    The schema is the live step's own whenever it carries one, so a later
    form's rejection shows that form; a fresh introspection flow is the
    fallback for a schema-less step. ``is_reconfigure`` skips that fallback
    too (``helper_type`` carries the integration domain there) and makes the
    prose name the integration instead of a helper, because this path also
    serves ``ha_set_integration(reconfigure=True)``. ``flow_stays_open``
    (``ha_set_integration``'s one step per call) skips the fallback as well
    and says the rejected flow is still open.

    Always raises ``ToolError`` — never returns.
    """
    parsed = _parse_flow_api_error(api_error)
    field_errors = parsed["field_errors"]
    status_code = api_error.status_code or 0

    context = _build_flow_error_context(
        flow_id,
        status_code,
        helper_type,
        menu_choice,
        current_step,
        submitted,
        parsed["raw"],
    )

    suggestions: list[str] = []
    message: str

    current_schema = None
    if current_step is not None:
        step_schema = current_step.get("data_schema")
        if isinstance(step_schema, list):
            current_schema = step_schema

    if current_schema is not None or is_reconfigure or flow_stays_open:
        # The live step is the form HA rejected: a fresh introspection would
        # show the helper's first setup form instead, a different form in a
        # multi-step, options or reconfigure flow.
        schema = current_schema
    else:
        info = await fetch_helper_flow_info(client, helper_type, menu_choice)
        schema = info.get("schema")
    # An options/reconfigure step's schema carries the persisted values in
    # description.suggested_value — under redact_secrets those must not ride
    # into the error context verbatim (#2157). Deep-copies, so the live
    # flow_result is untouched.
    if schema is not None and redaction_enabled():
        schema = redact_flow_schema(schema)

    # Issue #1149: the schema rides with field_errors too — what failed plus
    # what's accepted is enough for self-correction.
    if schema is not None:
        context["data_schema"] = schema
    if field_errors:
        # Structured field errors — tell the caller which fields failed.
        # HA names fields only when the caller's input failed its schema.
        code = ErrorCode.VALIDATION_INVALID_PARAMETER
        context["field_errors"] = field_errors
        readable = ", ".join(f"{k}: {v}" for k, v in field_errors.items())
        subject = _flow_error_subject(
            helper_type, is_reconfigure=is_reconfigure, validation=True
        )
        message = f"{subject} failed — {readable}"
        suggestions.append(
            "Fix the field(s) listed in 'field_errors' and retry the call."
        )
    else:
        # Unstructured — attach the data_schema so the LLM has something to use.
        code = ErrorCode.SERVICE_CALL_FAILED
        subject = _flow_error_subject(
            helper_type, is_reconfigure=is_reconfigure, validation=False
        )
        message = (
            f"Home Assistant rejected the {subject} request "
            f"({status_code}): {parsed['message']}"
        )
        if schema is not None:
            suggestions.append(
                "Inspect 'data_schema' in this error to see the fields HA expects, "
                "then retry with a corrected config."
            )

    if is_reconfigure:
        context["status"] = ReconfigureStatus.APPLY_FAILED
    if flow_stays_open:
        suggestions.append(
            "The flow is still open: retry with flow_id, or end it with "
            "flow_id and abort=True."
        )

    raise_tool_error(
        create_error_response(
            code,
            message,
            suggestions=suggestions,
            context=context,
        )
    )


def _flow_failure_context(
    flow_id: str, current_step: dict[str, Any], *, is_reconfigure: bool
) -> dict[str, Any]:
    context: dict[str, Any] = {"flow_id": flow_id, "details": current_step}
    if is_reconfigure:
        context["status"] = ReconfigureStatus.APPLY_FAILED
    return context


def redacted_step(step: dict[str, Any]) -> dict[str, Any]:
    """``step`` with its form's stored secrets redacted under redact_secrets.

    A form carries the persisted values in ``suggested_value`` (#2157).
    """
    schema = step.get("data_schema")
    if isinstance(schema, list) and redaction_enabled():
        return {**step, "data_schema": redact_flow_schema(schema)}
    return step


async def raise_form_errors(
    client: Any,
    flow: FlowRef | None,
    flow_id: str,
    current_step: dict[str, Any],
    *,
    is_reconfigure: bool = False,
    flow_stays_open: bool = False,
) -> NoReturn:
    """Raise for a form HA returned with ``errors``, with Core's text for each
    and the form's ``fields`` in the describe shape."""
    # describe imports config_entry_flow, which imports this module.
    from ha_mcp.runtime.flow_description import compact_schema

    errors = current_step["errors"]
    context: dict[str, Any] = {
        "flow_id": flow_id,
        "step_id": current_step.get("step_id"),
        "errors": errors,
        "fields": compact_schema(current_step.get("data_schema") or []),
    }
    if is_reconfigure:
        context["status"] = ReconfigureStatus.APPLY_FAILED
    if isinstance(errors, dict):
        texts = await _flow_texts(client, flow, current_step, "error", errors)
        if warnings := texts.pop("warnings", None):
            context["warnings"] = warnings
        if texts:
            context["error_text"] = texts
    suggestions = ["Fix the field errors and retry with corrected values"]
    if flow_stays_open:
        suggestions.append(
            "The flow is still open: retry with flow_id, or end it with "
            "flow_id and abort=True."
        )
    raise_tool_error(
        create_error_response(
            ErrorCode.VALIDATION_INVALID_PARAMETER,
            "Form validation failed",
            suggestions=suggestions,
            context=context,
        )
    )


async def abort_reason_text(
    client: Any, flow: FlowRef | None, current_step: dict[str, Any]
) -> dict[str, Any]:
    """``{"reason_text": ...}`` for an abort step, or ``{}`` without a string."""
    return await _flow_texts(
        client, flow, current_step, "abort", {"reason_text": current_step.get("reason")}
    )


async def progress_action_text(
    client: Any, flow: FlowRef | None, current_step: dict[str, Any]
) -> dict[str, Any]:
    """``{"progress_action_text": ...}`` for a progress step, or ``{}``."""
    return await _flow_texts(
        client,
        flow,
        current_step,
        "progress",
        {"progress_action_text": current_step.get("progress_action")},
    )


async def raise_flow_abort(
    client: Any,
    flow: FlowRef | None,
    flow_id: str,
    current_step: dict[str, Any],
    *,
    is_reconfigure: bool = False,
) -> NoReturn:
    """Raise the structured error for an ABORT flow step."""
    raise_tool_error(
        create_error_response(
            ErrorCode.SERVICE_CALL_FAILED,
            f"Flow aborted: {current_step.get('reason')}",
            context={
                **_flow_failure_context(
                    flow_id, current_step, is_reconfigure=is_reconfigure
                ),
                **await abort_reason_text(client, flow, current_step),
            },
        )
    )


_RETRYABLE_GATEWAY_STATUS = frozenset({502, 503, 504})


async def _submit_step(
    submit_fn: Any,
    flow_id: str,
    payload: dict[str, Any],
    *,
    client: Any,
    helper_type: str | None,
    last_menu_choice: str | None,
    current_step: dict[str, Any],
    is_reconfigure: bool = False,
    flow_stays_open: bool = False,
) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(submit_fn(flow_id, payload), timeout=20.0)
    except HomeAssistantAPIError as api_err:
        if api_err.status_code in (400, 422):
            await _raise_flow_api_error(
                api_err,
                client=client,
                flow_id=flow_id,
                helper_type=helper_type,
                menu_choice=last_menu_choice,
                current_step=current_step,
                submitted=payload,
                is_reconfigure=is_reconfigure,
                flow_stays_open=flow_stays_open,
            )
        status = api_err.status_code or 0
        if status in _RETRYABLE_GATEWAY_STATUS or (is_reconfigure and status >= 500):
            # 502/503/504 mean no answer came back: the submit may have reached
            # Home Assistant and committed. On reconfigure any 5xx may follow
            # the step's own write to the entry; other kinds are written by Core
            # only after the step returns (a create flow's async_on_create_entry
            # can still 500 after the save, which this does not tell apart).
            # Anything else re-raises: HA answered.
            _raise_no_answer(
                api_err,
                flow_id=flow_id,
                payload=payload,
                current_step=current_step,
                error_code=ErrorCode.SERVICE_CALL_FAILED,
                detail=f"HTTP {status}",
            )
        raise
    except no_answer_errors() + (TimeoutError,) as no_answer:
        # Every class here is evidence that NO ANSWER came back — see
        # no_answer_errors() in rest_client.py — as opposed to Home Assistant
        # answering with a rejection (which the 400/422 branch above handles).
        # The submit is the call that commits (creates the entry, saves the
        # options, or probes and reloads on reconfigure), so losing the answer
        # to it is precisely the applied_but_unverified ambiguity: HA may
        # already have committed, and a retry can repeat the change.
        # rest_client funnels every httpx transport failure into
        # HomeAssistantConnectionError, so a connection reset after the POST
        # reached HA lands here too. Callers keep the flow open on this status
        # (leaves_flow_open; the snapshot paths on their "unknown" apply_status).
        _raise_no_answer(
            no_answer,
            flow_id=flow_id,
            payload=payload,
            current_step=current_step,
            error_code=ErrorCode.TIMEOUT_OPERATION
            if isinstance(no_answer, TimeoutError)
            else ErrorCode.SERVICE_CALL_FAILED,
            detail=type(no_answer).__name__,
        )
        raise  # not reached; an explicit end of this path for CodeQL


def _raise_no_answer(
    cause: BaseException,
    *,
    flow_id: str,
    payload: dict[str, Any],
    current_step: dict[str, Any],
    error_code: ErrorCode,
    detail: str,
) -> NoReturn:
    """Raise ``applied_but_unverified`` for a submit or poll whose answer was lost.

    Carrying the post-commit status is what suppresses the flow abort: see
    ``leaves_flow_open``.
    """
    raise_tool_error(
        create_error_response(
            error_code,
            "Flow submission got no answer from Home "
            f"Assistant ({detail}); the change may have been applied",
            suggestions=[
                "Do not retry automatically: a retry can create a duplicate "
                "entry or repeat the change. Check the config entry in Home "
                "Assistant first."
            ],
            context={
                "flow_id": flow_id,
                "status": ReconfigureStatus.APPLIED_BUT_UNVERIFIED,
                "submitted_keys": sorted(payload),
                "details": redacted_step(current_step),
            },
        )
    )
