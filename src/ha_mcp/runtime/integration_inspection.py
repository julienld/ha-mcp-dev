"""Invocation-local backend seams for integration inspection."""

import logging
from typing import Any, NoReturn

from ha_mcp.tool_api import BackendTools

from .errors import raise_classified
from .flows.introspect import abort_probe_flow
from .flows.session import FlowSession
from .integration_components import (
    _split_component_entry_row as _split_component_entry_row,
)
from .integration_schema import options_from_form_flow

logger = logging.getLogger(__name__)


async def fetch_entry_options_with_status(
    client: Any, entry_id: str, *, quiet: bool = False
) -> tuple[dict[str, Any], bool]:
    """Read a config entry's ``options`` and report whether the probe succeeded.

    Starts the entry's OptionsFlow, harvests ``{name: current_value}`` from
    its first-step form via :func:`options_from_form_flow` (the persisted
    option from ``description.suggested_value``, falling back to the schema
    ``default``), and aborts the flow so it doesn't sit half-open. Returns
    ``(options, ok)`` so callers can tell a probe *failure* apart from a
    genuinely-empty options form — both yield ``{}`` for ``options``, but
    ``ok`` is:

    - ``True`` only when a form first-step was read (even if it harvested no
      fields: a genuinely-empty options form is a successful read).
    - ``False`` when the OptionsFlow could not be read into options: the flow
      raised, or its first step was not a form (a menu / abort / create_entry),
      so no options could be harvested.

    The flag lets the caller surface degraded reads instead of passing ``{}``
    off as real options: ``smart_search`` flips ``partial`` when a probe
    fails mid-search. The abort in ``finally`` is cleanup; a failed abort does
    not flip ``ok`` (the options were already harvested).

    Home Assistant does not expose ``ConfigEntry.options`` through any
    read-only REST or WebSocket endpoint — ``/api/config/config_entries/entry``
    deliberately omits the field. The closest approximation that the HA UI
    itself uses is the OptionsFlow's first-step ``data_schema``: HA injects
    the persisted options into each field's ``description.suggested_value``
    (via ``add_suggested_values_to_schema``), which
    :func:`options_from_form_flow` prefers over the static schema
    ``default`` (issue #1575).

    Probe failures log at ``warning`` unless ``quiet=True``, which demotes
    them to ``debug`` for a bulk fan-out: ``smart_search`` probes one entry
    per flow helper on every ``ha_search``, and a per-entry warning there
    would spam the log on routine searches.

    Exposed at module level (not as a method) so
    ``smart_search._search_flow_helpers`` can probe flow-helper config
    without instantiating ``IntegrationTools``.
    """
    log_probe_failure = logger.debug if quiet else logger.warning
    flow_id: str | None = None
    try:
        flow = await client.start_options_flow(entry_id)
        flow_id = flow.get("flow_id")
        flow_type = flow.get("type")
        if flow_type != "form":
            log_probe_failure(
                f"OptionsFlow for {entry_id} returned type={flow_type!r}, "
                f"not a form — cannot extract options"
            )
            return {}, False
        return options_from_form_flow(flow), True
    except Exception as exc:  # noqa: BLE001
        log_probe_failure(
            f"Failed to fetch options for {entry_id}: {type(exc).__name__}: {exc}"
        )
        return {}, False
    finally:
        if flow_id:
            await abort_probe_flow(client.abort_options_flow, flow_id, quiet=quiet)


class IntegrationInspection(BackendTools):
    def _flow_client(self) -> FlowSession:
        return FlowSession(
            self.backend,
            self.context,
            entry_guard=getattr(self, "_entry_write_guard", None),
        )

    async def _component_entries(self, **query: Any) -> list[dict[str, Any]] | None:
        result = await self.backend.execute(
            "integrations.entries",
            {key: value for key, value in query.items() if value is not None},
            self.context,
        )
        return result["entries"] if result is not None else None

    def _raise_inspection_error(
        self,
        error: Exception,
        context: dict[str, Any] | None = None,
        *,
        suggestions: list[str] | None = None,
    ) -> NoReturn:
        raise_classified(error, context, suggestions=suggestions)
