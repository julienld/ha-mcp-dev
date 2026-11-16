"""Exact manifest wheel receipts preserve a loaded native generation on rollback."""

import json
import threading
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_mcp_tools import embedded_server as es
from custom_components.ha_mcp_tools.const import DATA_LAST_PIP_SPEC, DATA_REINSTALL_REQUESTED, OPT_PIP_SPEC

from ._embedded_server_core import PackageIndex, new_manager, pin, package_step
from ._embedded_server_core import package_index as package_index
from .test_paired_wheel import _DIGEST, _SPEC, _URL


@pytest.fixture
async def managed(hass: HomeAssistant, package_index: PackageIndex, tmp_path, monkeypatch):

    from custom_components.ha_mcp_tools import paired_wheel

    (tmp_path / "installed" / "ha_mcp").mkdir(parents=True)
    monkeypatch.setattr(paired_wheel.wheel_payload, "sys", SimpleNamespace(modules={}))

    pin(hass, _SPEC)
    manager, entry = await new_manager(hass, data={DATA_LAST_PIP_SPEC: _SPEC})
    env = package_index
    env.dists["ha-mcp"] = "9.0.0.dev1"
    monkeypatch.setattr(es, "native_bound_version", lambda: "9.0.0.dev1")
    receipt = {"url": _URL, "archive_info": {"hashes": {"sha256": _DIGEST}}}
    threads = []

    def distribution(_name):
        threads.append(threading.get_ident())
        return SimpleNamespace(
            version="9.0.0.dev1",
            metadata={"Name": "ha-mcp"},
            read_text=lambda _filename: json.dumps(receipt),
            locate_file=lambda member: tmp_path / "installed" / member,
        )

    monkeypatch.setattr(paired_wheel.importlib.metadata, "distribution", distribution)

    return manager, env, entry, receipt, threads


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
