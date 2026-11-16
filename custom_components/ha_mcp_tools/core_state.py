"""Small live Core state and service-name readers shared by all transports."""

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant

from .core_registry import _call_no_arg, _state_as_dict, _state_get


def service_names(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Service catalog in the ``client.get_services()`` list shape.

    The consumer's ``_build_service_stats`` reads only the per-domain service
    *names*, so each service maps to an empty dict — keeps the frame small while
    preserving the ``{domain, services: {name: {...}}}`` structure.
    """
    services = _call_no_arg(getattr(hass, "services", None), "async_services")
    if not isinstance(services, Mapping):
        return []
    out: list[dict[str, Any]] = []
    for domain, svcs in services.items():
        names = list(svcs.keys()) if isinstance(svcs, Mapping) else []
        out.append({"domain": domain, "services": {name: {} for name in names}})
    return out


def read_states(hass: HomeAssistant, entity_ids: list[str]) -> dict[str, Any]:
    """Return Core state records with live ``last_reported`` and missing IDs.

    Core caches the remaining wire body; the shared serializer refreshes the
    repeated-report timestamp without changing datetime encoding or attributes.
    """
    states: dict[str, Any] = {}
    missing: list[str] = []
    for entity_id in entity_ids:
        state = _state_get(hass, entity_id)
        if state is None:
            missing.append(entity_id)
            continue
        as_dict = _state_as_dict(state)
        if as_dict is None:
            # A live state that could not be serialized (core drift) goes to
            # ``missing`` rather than emitting a null state indistinguishable from
            # a real value — the server maps ``missing`` onto its per-id contract.
            missing.append(entity_id)
            continue
        states[entity_id] = as_dict
    return {"states": states, "missing": missing}
