"""The upgrade bench must retain installed dependencies and close HTTP pools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.native.upgrade_paths import run as bench
from tests.native.upgrade_paths.contracts import PHASES, PROFILES
from tests.native.upgrade_paths.readiness import endpoint_ready


@pytest.mark.parametrize("refused", [False, True])
async def test_candidate_restarts_retain_installation_and_capture_every_completed_setup(
    tmp_path, monkeypatch, refused
):
    containers, captures, clients, events = [], [], [], []

    def start(*args, candidate, **kwargs):
        wrapped = SimpleNamespace(
            start=Mock(side_effect=lambda: events.append("restart"))
        )
        container = SimpleNamespace(
            get_wrapped_container=lambda: wrapped, candidate=candidate
        )
        containers.append(container)
        events.append("start")
        return container

    def stop(container, *args, remove=True):
        events.append("remove" if remove else "stop")

    def capture(container):
        captures.append(container)
        events.append("capture")
        if refused:
            raise bench.UpgradeFailure("dependency_observation_refused")

    async def ready(*args):
        events.append("ready")
        return dict.fromkeys(
            (
                "identity",
                "revision",
                "core_version",
                "core_image_id",
                "component_sha256",
                "package_sha256",
                "ha_mcp_version",
                "private_versions",
                "runtime",
                "entry_id",
            ),
            "receipt",
        )

    async def phase(http, *args, **kwargs):
        clients.append(http)
        events.append("client")
        return {"passed": True}, {}

    monkeypatch.setattr(bench, "start", start)
    monkeypatch.setattr(bench, "stop", stop)
    # A replaceable observation seam keeps this lifecycle test free of Docker.
    monkeypatch.setattr(bench, "capture_setup", capture, raising=False)
    monkeypatch.setattr(bench, "ready", ready)
    monkeypatch.setattr(bench, "phase", phase)
    monkeypatch.setattr(bench, "command", Mock())
    monkeypatch.setattr(
        bench,
        "seed_profile",
        lambda *args: ({"token": "token", "user_id": "owner"}, {}),
    )
    monkeypatch.setattr(
        bench,
        "entry_identity",
        lambda *args: ({"data": {"secret_path": "/unchanged"}}, "identity"),
    )
    monkeypatch.setattr(bench, "receipt", lambda *args: {})
    monkeypatch.setattr(
        bench, "install_candidate", lambda *args: tmp_path / "candidate.whl"
    )
    monkeypatch.setattr(bench, "enroll_main", AsyncMock(return_value=("hash", {})))
    monkeypatch.setattr(bench, "choose_native", AsyncMock())
    args = SimpleNamespace(
        baseline_source=tmp_path,
        baseline_revision="main",
        candidate_source=tmp_path,
        candidate_revision="native",
    )
    result = {"phases": {}}
    await bench.profile_run(
        args,
        tmp_path,
        PROFILES[0],
        (tmp_path / "main.whl", tmp_path),
        "image",
        "nonce",
        result,
    )
    if refused:
        assert (
            result["phases"]["upgraded"]["failure"] == "dependency_observation_refused"
        )
        assert containers[1].get_wrapped_container().start.call_count == 0
        assert captures == [containers[1]]
        assert events[-1] == "remove"
        return
    assert all(result["phases"][name]["passed"] for name in PHASES), result
    assert len(containers) == 2, (
        "Recreating the candidate loses Core 2026.11's installed Python environment"
    )
    assert captures == [containers[1]] * 3, (
        "Every candidate boot must complete dependency qualification"
    )
    assert containers[1].get_wrapped_container().start.call_count == 2
    assert len({id(client) for client in clients}) == 4, (
        "A restarted server needs a fresh HTTP pool, with the same credentials"
    )
    assert all(client.is_closed for client in clients)
    assert events == [
        "start",
        "ready",
        "client",
        "remove",
        "start",
        "ready",
        "capture",
        "client",
        "stop",
        "restart",
        "ready",
        "capture",
        "client",
        "stop",
        "restart",
        "ready",
        "capture",
        "client",
        "remove",
    ]


@pytest.mark.parametrize(
    "mode,provider",
    [("none", None), ("ha_auth", "resource_server"), ("legacy", "oauth_provider")],
)
def test_running_manager_does_not_imply_ready_webhook_and_authentication(
    mode, provider
):
    entry = SimpleNamespace(
        state="setup_in_progress",
        data={"webhook_id": "w"},
        options={"webhook_auth": mode},
    )
    cfg = {"webhook_id": "w", "auth_mode": mode}
    hass = SimpleNamespace(
        is_running=False,
        data={
            "ha_mcp_tools": {"webhook": cfg},
            "webhook": {"w": SimpleNamespace(domain="ha_mcp_tools")},
        },
    )
    assert not endpoint_ready(hass, entry)
    entry.state = "loaded"
    if provider:
        assert not endpoint_ready(hass, entry)
        cfg[provider] = object()
    assert not endpoint_ready(hass, entry)
    hass.is_running = True
    assert endpoint_ready(hass, entry)
    hass.data["webhook"].clear()
    assert not endpoint_ready(hass, entry)


@pytest.mark.parametrize("http_status", [401, 500])
async def test_readiness_preserves_probe_errors_without_waiting_for_startup_timeout(
    monkeypatch, http_status
):
    from tests.native.upgrade_paths import exercise

    http = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                status_code=http_status,
                json=Mock(
                    side_effect=AssertionError("Private response must not be read")
                ),
            )
        )
    )
    monkeypatch.setattr(
        exercise, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 721]))
    )
    sleep = AsyncMock()
    monkeypatch.setattr(exercise, "asyncio", SimpleNamespace(sleep=sleep))
    with pytest.raises(
        exercise.UpgradeFailure, match="runtime_probe_http_refused"
    ) as error:
        await exercise.ready(
            http, "http://127.0.0.1:1234", "private-token", {}, "legacy"
        )
    assert error.value.diagnostic == {"http_status": http_status}
    http.get.assert_awaited_once()
    sleep.assert_not_awaited()
