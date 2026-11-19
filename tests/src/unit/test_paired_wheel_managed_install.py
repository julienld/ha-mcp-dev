"""Exact manifest wheel receipts preserve a loaded native generation on rollback."""

import threading

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_mcp_tools import embedded_server as es
from custom_components.ha_mcp_tools.const import DATA_REINSTALL_REQUESTED, OPT_PIP_SPEC

from ._embedded_server_core import package_step
from ._paired_wheel_core import WHEEL_SPEC as _SPEC
from ._paired_wheel_core import managed as managed
from ._paired_wheel_core import package_index as package_index


async def test_exact_hashed_manifest_wheel_does_not_reinstall_on_native_to_legacy_switch(
    managed,
):
    manager, env, _entry, _receipt, threads = managed
    await package_step(manager)
    assert env.calls == []
    assert threads and all(thread != threading.get_ident() for thread in threads)


@pytest.mark.parametrize(
    "reason",
    [
        "override",
        "explicit_reinstall",
        "wrong_receipt",
        "conflicting_distribution",
        "changed_native_generation",
    ],
)
async def test_requested_or_unproven_package_change_still_requires_Core_restart(
    hass: HomeAssistant, managed, reason, monkeypatch
):
    manager, env, entry, receipt, _threads = managed
    if reason == "override":
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, OPT_PIP_SPEC: _SPEC}
        )
        manager = es.EmbeddedServerManager(hass, entry)
    elif reason == "explicit_reinstall":
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, DATA_REINSTALL_REQUESTED: True}
        )
    elif reason == "wrong_receipt":
        receipt["archive_info"]["hashes"]["sha256"] = "0" * 64
    elif reason == "conflicting_distribution":
        env.dists["ha-mcp-dev"] = "9.0.0.dev1"
    else:
        monkeypatch.setattr(es, "native_bound_version", lambda: "9.0.0.dev2")
    with pytest.raises(es.EmbeddedServerError, match="restart Home Assistant"):
        await manager.async_start()
    assert env.calls == []
