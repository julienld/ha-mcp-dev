"""Paired-wheel receipts and real-Core package-manager fixtures."""

import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_mcp_tools import embedded_server as es
from custom_components.ha_mcp_tools.const import DATA_LAST_PIP_SPEC

from ._embedded_server_core import PackageIndex, new_manager, pin
from ._embedded_server_core import package_index as package_index

WHEEL_URL = "https://github.com/julienld/ha-mcp-native/releases/download/9.0.0.dev1/ha_mcp-9.0.0.dev1-py3-none-any.whl"
WHEEL_DIGEST = "abc01234" * 8
WHEEL_SPEC = "ha-mcp @ " + WHEEL_URL + "#sha256=" + WHEEL_DIGEST


@pytest.fixture
def paired(monkeypatch, tmp_path):
    path = (
        Path(__file__).resolve().parents[3]
        / "custom_components/ha_mcp_tools/paired_wheel.py"
    )
    package_name = "paired_wheel_contract"
    package = ModuleType(package_name)
    package.__path__ = [str(path.parent)]
    monkeypatch.setitem(sys.modules, package_name, package)
    spec = importlib.util.spec_from_file_location(package_name + ".paired_wheel", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = importlib.import_module(package_name + ".wheel_payload")
    monkeypatch.setattr(payload, "sys", SimpleNamespace(modules={}))
    site = tmp_path / "installed"
    (site / "ha_mcp").mkdir(parents=True)
    receipt = {"url": WHEEL_URL, "archive_info": {"hashes": {"sha256": WHEEL_DIGEST}}}
    distribution = SimpleNamespace(
        version="9.0.0.dev1",
        metadata={"Name": "ha-mcp"},
        read_text=lambda _name: json.dumps(receipt),
        locate_file=lambda member: site / member,
    )
    monkeypatch.setattr(
        module.importlib.metadata, "distribution", lambda _name: distribution
    )
    return module, receipt, distribution


@pytest.fixture
async def managed(
    hass: HomeAssistant, package_index: PackageIndex, tmp_path, monkeypatch
):

    from custom_components.ha_mcp_tools import paired_wheel

    (tmp_path / "installed" / "ha_mcp").mkdir(parents=True)
    monkeypatch.setattr(paired_wheel.wheel_payload, "sys", SimpleNamespace(modules={}))

    pin(hass, WHEEL_SPEC)
    manager, entry = await new_manager(hass, data={DATA_LAST_PIP_SPEC: WHEEL_SPEC})
    env = package_index
    env.dists["ha-mcp"] = "9.0.0.dev1"
    monkeypatch.setattr(es, "native_bound_version", lambda: "9.0.0.dev1")
    receipt = {"url": WHEEL_URL, "archive_info": {"hashes": {"sha256": WHEEL_DIGEST}}}
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
