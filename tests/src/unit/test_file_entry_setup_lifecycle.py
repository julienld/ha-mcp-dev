"""Tools-entry setup owns file authority through failure, retry and cancellation."""

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ha_mcp.tool_api import CallContext, ToolFailure

from .test_native_engine_backend import native as native
from .test_native_file_access import files as files
from .test_native_filesystem import filesystem as filesystem


@pytest.fixture
def setup_world(filesystem, monkeypatch):
    _service, manager, previous, _target = filesystem
    component = importlib.import_module("custom_components.ha_mcp_tools")
    hass = manager.hass
    hass.data["ha_mcp_tools"].pop("file_access_owner")
    unsubscribe = Mock()
    hass.bus = SimpleNamespace(async_listen_once=Mock(return_value=unsubscribe))
    hass.services.async_register = Mock()

    def register_admin(owner, domain, service, handler, **kwargs):
        assert owner is hass
        hass.services.async_register(domain, service, handler, **kwargs)

    monkeypatch.setattr(
        component.ha_service, "async_register_admin_service", register_admin
    )
    entry = SimpleNamespace(
        entry_id="tools-entry",
        data={},
        disabled_by=None,
        title="Custom tools",
        async_on_unload=Mock(),
    )
    hass.config_entries = SimpleNamespace(async_get_entry=lambda _id: entry)
    for name, result in (
        ("_load_or_create_caller_token", "fixture-capability"),
        ("_load_allowed_paths", []),
        ("_load_extra_yaml_keys", []),
    ):
        monkeypatch.setattr(component, name, AsyncMock(return_value=result))
    monkeypatch.setattr(component, "_migrate_legacy_backup_dir", lambda _path: (0, 0))
    for name in (
        "register_find_yaml_key",
        "register_edit_file",
        "async_register_commands",
    ):
        monkeypatch.setattr(component, name, Mock())
    monkeypatch.setattr(component, "async_register_entry_device", AsyncMock())
    return component, manager, entry, previous, unsubscribe


async def test_file_authority_is_unavailable_until_setup_succeeds(
    setup_world, monkeypatch
):
    component, manager, entry, _previous, _unsubscribe = setup_world
    from custom_components.ha_mcp_tools.native_operations.file_entry import (
        NativeFileEntry,
    )

    async def finalize(*_args, **_kwargs):
        with pytest.raises(ToolFailure, match="not set up"):
            await NativeFileEntry(manager, CallContext("owner"))._owner()

    monkeypatch.setattr(component, "async_register_entry_device", finalize)
    assert await component.async_setup_entry(manager.hass, entry)
    owner = await NativeFileEntry(manager, CallContext("owner"))._owner()
    assert owner.active and owner.entry is entry
    await component.async_unload_entry(manager.hass, entry)


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_late_setup_failure_revokes_and_detaches_exact_owner(
    setup_world, monkeypatch, failure
):
    component, manager, entry, _previous, unsubscribe = setup_world
    owners = []

    async def fail(*_args, **_kwargs):
        owners.append(manager.hass.data["ha_mcp_tools"]["file_access_owner"])
        raise failure("late setup failure")

    monkeypatch.setattr(component, "async_register_entry_device", fail)
    with pytest.raises(failure, match="late setup failure"):
        await component.async_setup_entry(manager.hass, entry)
    assert owners and not owners[0].active and not owners[0].pending
    assert "file_access_owner" not in manager.hass.data["ha_mcp_tools"]
    entry.async_on_unload.call_args.args[0]()
    unsubscribe.assert_called_once()


async def test_setup_retry_cannot_replace_undrained_file_owner(setup_world):
    component, manager, entry, previous, _unsubscribe = setup_world
    manager.hass.data["ha_mcp_tools"]["file_access_owner"] = previous
    previous.stop_seconds = 0
    started, release = asyncio.Event(), asyncio.Event()

    async def invoke(**_kwargs):
        started.set()
        await release.wait()
        return {"success": True}

    pending = asyncio.create_task(previous.run_owned(invoke, None, writes=False))
    try:
        await started.wait()
        with pytest.raises(RuntimeError, match="remains owned"):
            await component.async_setup_entry(manager.hass, entry)
        assert manager.hass.data["ha_mcp_tools"]["file_access_owner"] is previous
        assert not previous.active and previous.pending
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
    assert await component.async_setup_entry(manager.hass, entry)
    replacement = manager.hass.data["ha_mcp_tools"]["file_access_owner"]
    assert replacement is not previous and replacement.active
    await component.async_unload_entry(manager.hass, entry)


async def test_shutdown_during_setup_cannot_reactivate_file_authority(
    setup_world, monkeypatch
):
    component, manager, entry, _previous, _unsubscribe = setup_world

    async def stopping(*_args, **_kwargs):
        await manager.hass.bus.async_listen_once.call_args.args[1](None)

    monkeypatch.setattr(component, "async_register_entry_device", stopping)
    with pytest.raises(RuntimeError, match="changed during entry setup"):
        await component.async_setup_entry(manager.hass, entry)
    assert "file_access_owner" not in manager.hass.data["ha_mcp_tools"]


async def test_cancelled_setup_retains_previous_owner_until_issued_work_finishes(
    setup_world, monkeypatch
):
    component, manager, entry, previous, _unsubscribe = setup_world
    manager.hass.data["ha_mcp_tools"]["file_access_owner"] = previous
    started, release, stopping = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_stop = previous.async_stop

    async def stop():
        stopping.set()
        await original_stop()

    async def invoke(**_kwargs):
        started.set()
        await release.wait()
        return {"success": True}

    monkeypatch.setattr(previous, "async_stop", stop)
    pending = asyncio.create_task(previous.run_owned(invoke, None, writes=False))
    setup = None
    try:
        await started.wait()
        setup = asyncio.create_task(component.async_setup_entry(manager.hass, entry))
        await asyncio.wait_for(stopping.wait(), 1)
        setup.cancel()
        await asyncio.sleep(0)
        setup.cancel()
        await asyncio.sleep(0)
        assert not setup.done() and previous.pending and not previous.active
        assert manager.hass.data["ha_mcp_tools"]["file_access_owner"] is previous
    finally:
        release.set()
        results = await asyncio.gather(
            pending, *([setup] if setup is not None else []), return_exceptions=True
        )
    assert isinstance(results[-1], asyncio.CancelledError)
    assert not previous.pending
    assert await component.async_setup_entry(manager.hass, entry)
    await component.async_unload_entry(manager.hass, entry)


@pytest.mark.parametrize(
    ("service", "arguments"),
    [
        ("list_files", {"path": "www"}),
        ("read_file", {"path": "www/notes.txt"}),
        (
            "write_file",
            {"path": "www/notes.txt", "content": "updated", "overwrite": True},
        ),
        ("delete_file", {"path": "www/notes.txt"}),
    ],
)
async def test_registered_file_handler_retains_its_entry_lifetime(
    setup_world, monkeypatch, service, arguments
):
    component, manager, entry, _previous, _unsubscribe = setup_world
    hass = manager.hass
    target = Path(hass.config.path("www", "notes.txt"))
    io = Mock(wraps=hass.async_add_executor_job)
    monkeypatch.setattr(hass, "async_add_executor_job", io)
    call = SimpleNamespace(
        data={**arguments, component.CALLER_TOKEN_FIELD: "fixture-capability"}
    )
    handlers = []

    async def finalize(*_args, **_kwargs):
        registered = {
            registration.args[1]: registration.args[2]
            for registration in hass.services.async_register.call_args_list
            if registration.args[0] == component.DOMAIN
        }
        handler = registered[service]
        handlers.append(handler)
        before_io = io.call_count
        refused = await handler(call)
        assert refused["error"]["code"] == "INTEGRATION_STOPPING"
        assert io.call_count == before_io
        assert await asyncio.to_thread(target.read_text) == "before"

    monkeypatch.setattr(component, "async_register_entry_device", finalize)
    assert await component.async_setup_entry(hass, entry)
    handler = handlers[0]
    try:
        result = await handler(call)
        assert result["success"] is True
        if service == "read_file":
            assert result["content"] == "before"
        elif service == "list_files":
            assert result["count"] == 1
        elif service == "write_file":
            assert await asyncio.to_thread(target.read_text) == "updated"
        else:
            assert not await asyncio.to_thread(target.exists)
    finally:
        await component.async_unload_entry(hass, entry)

    before_io = io.call_count
    refused = await handler(call)
    assert refused["success"] is False and io.call_count == before_io

    # A subsequent setup restores the valid service credential. Cached handlers
    # must still reject their old owner rather than gain the new entry's lifetime.
    monkeypatch.setattr(component, "async_register_entry_device", AsyncMock())
    assert await component.async_setup_entry(hass, entry)
    try:
        before_io = io.call_count
        refused = await handler(call)
        assert refused["error"]["code"] == "INTEGRATION_STOPPING"
        assert io.call_count == before_io
    finally:
        await component.async_unload_entry(hass, entry)
