"""Qualification must boot the selected runtime under a real fixture identity."""

import importlib.util
import json
import shlex
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.src.e2e import _conftest_testcontainer as container_harness
from tests.src.e2e._conftest_native_runtime import (
    attest_native_runtime,
    configure_native_entry,
    native_dependency_command,
)


@pytest.fixture(autouse=True)
def isolated_attestation_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2E_ATTESTATION_DIRECTORY", raising=False)
    monkeypatch.delenv("E2E_EXPECTED_CORE_VERSION", raising=False)
    monkeypatch.delenv("E2E_EXPECTED_ARCH", raising=False)


@pytest.mark.parametrize(
    "target,error",
    [
        ({"E2E_EXPECTED_CORE_VERSION": "2026.11.0"}, "Core version mismatch"),
        ({"E2E_EXPECTED_ARCH": "arm64"}, "architecture mismatch"),
        (
            {"E2E_EXPECTED_CORE_VERSION": "2026.10.0", "E2E_EXPECTED_ARCH": "amd64"},
            None,
        ),
    ],
)
def test_haos_attestation_checks_the_requested_core_and_architecture(
    monkeypatch, tmp_path, target, error
):
    from tests.src import haos_candidate

    for name in ("E2E_EXPECTED_CORE_VERSION", "E2E_EXPECTED_ARCH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in target.items():
        monkeypatch.setenv(name, value)
    observed = {
        "manager": "NativeServerManager",
        "runtime": "native",
        "running": True,
        "on_core_loop": True,
        "legacy_listener": False,
        "legacy_thread": False,
        "admin_token_present": False,
        "library_version": "fixture-version",
        "revision": "a" * 40,
        "core_version": "2026.10.0",
        "architecture": "x86_64",
    }
    monkeypatch.setattr(
        haos_candidate, "verify_candidate_artifacts", lambda _assets: observed
    )
    monkeypatch.setattr(
        haos_candidate.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=Mock(), json=lambda: observed
        ),
    )
    destination = tmp_path / "diagnostics"
    monkeypatch.setattr(haos_candidate, "Path", lambda _path: destination)
    if error:
        with pytest.raises(AssertionError, match=error):
            haos_candidate.attest_native_runtime(
                "http://fixture.test", "fixture", tmp_path
            )
        assert not destination.exists()
    else:
        haos_candidate.attest_native_runtime("http://fixture.test", "fixture", tmp_path)
        assert json.loads((destination / "native-runtime.json").read_text()) == observed


@pytest.fixture
def container_build(tmp_path, monkeypatch):
    container = Mock()
    for method in (
        "with_exposed_ports",
        "with_volume_mapping",
        "with_env",
        "with_kwargs",
    ):
        getattr(container, method).return_value = container
    constructor = Mock(return_value=container)
    monkeypatch.setattr(container_harness, "DockerContainer", constructor)
    monkeypatch.setattr(
        container_harness,
        "_collect_manifest_requirements",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(container_harness, "native_runtime_selected", lambda: True)
    monkeypatch.delenv("HA_TEST_PORT", raising=False)
    monkeypatch.delenv("HA_TEST_IMAGE", raising=False)
    monkeypatch.delenv("HA_IMAGE_GHCR", raising=False)

    def build() -> Mock:
        spec = importlib.util.spec_from_file_location(
            "selected_test_image", Path(__file__).parents[2] / "test_constants.py"
        )
        constants = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(constants)
        monkeypatch.setattr(container_harness, "HA_TEST_IMAGE", constants.HA_TEST_IMAGE)
        return container_harness._build_ha_testcontainer(
            tmp_path, True, "candidate.whl"
        )

    return SimpleNamespace(build=build, constructor=constructor)


def test_embedded_boot_uses_the_matrix_image_instead_of_the_stale_imported_pin(
    monkeypatch, container_build
):
    image = "ghcr.io/home-assistant/home-assistant:2026.8.0"
    monkeypatch.setenv("HA_IMAGE_GHCR", image)
    container_build.build()
    container_build.constructor.assert_called_once_with(image)


def test_explicit_test_image_override_still_wins_over_the_workflow_image(
    monkeypatch, container_build
):
    image = "registry.test/custom-core:candidate"
    monkeypatch.setenv("HA_TEST_IMAGE", image)
    monkeypatch.setenv(
        "HA_IMAGE_GHCR", "ghcr.io/home-assistant/home-assistant:2026.10.3"
    )
    container_build.build()
    container_build.constructor.assert_called_once_with(image)


def test_native_entrypoint_brackets_the_wheel_before_core_starts(container_build):
    container = container_build.build()
    entrypoint = container.with_kwargs.call_args.kwargs["entrypoint"]
    assert entrypoint[:2] == ["sh", "-c"]
    preparation, startup = entrypoint[2].split(" && ")
    assert shlex.split(preparation) == native_dependency_command("prepare")
    assert startup == "exec /init"


def _seed(config: Path, user: dict) -> Path:
    storage = config / ".storage"
    storage.mkdir()
    (storage / "auth").write_text(json.dumps({"data": {"users": [user]}}))
    path = storage / "core.config_entries"
    path.write_text(
        json.dumps(
            {
                "data": {
                    "entries": [
                        {
                            "entry_id": "server",
                            "data": {"admin_token": "old-fixture-token"},
                            "options": {"webhook_auth": "none"},
                        }
                    ]
                }
            }
        )
    )
    return path


@pytest.fixture
def owner() -> dict:
    return {
        "id": "owner",
        "is_owner": True,
        "is_active": True,
        "system_generated": False,
        "group_ids": ["system-admin"],
    }


def test_native_staging_uses_human_owner_without_retaining_a_token(tmp_path, owner):
    path = _seed(tmp_path, owner)
    configure_native_entry(tmp_path, "server")
    entry = json.loads(path.read_text())["data"]["entries"][0]
    assert entry["data"] == {"native_owner_user_id": "owner"}
    assert entry["options"]["runtime_mode"] == "native"
    assert entry["options"]["webhook_auth"] == "none"
    assert not entry["options"]["enable_llm_api"]
    assert not entry["options"]["enable_native_llm_import"]


@pytest.mark.parametrize(
    "change",
    [
        {"is_active": False},
        {"system_generated": True},
        {"group_ids": ["system-users"]},
        {"is_owner": False},
    ],
)
def test_missing_human_owner_refuses_before_rewriting_the_entry(
    tmp_path, owner, change
):
    path = _seed(tmp_path, {**owner, **change})
    before = path.read_bytes()
    with pytest.raises(ValueError, match="human fixture owner"):
        configure_native_entry(tmp_path, "server")
    assert path.read_bytes() == before


def test_a_responding_legacy_server_cannot_qualify_as_native(
    monkeypatch, tmp_path, candidate_config
):
    directory = tmp_path / "receipts"
    monkeypatch.setenv("E2E_ATTESTATION_DIRECTORY", str(directory))
    response = SimpleNamespace(
        raise_for_status=Mock(),
        json=lambda: {
            "manager": "EmbeddedServerManager",
            "runtime": "legacy",
            "running": True,
        },
    )
    monkeypatch.setattr(
        "tests.src.e2e._conftest_native_runtime.requests.get",
        lambda *args, **kwargs: response,
    )
    with pytest.raises(AssertionError, match="did not attest"):
        attest_native_runtime(
            "http://fixture.test", {"Authorization": "fixture"}, candidate_config
        )
    assert not directory.exists()


@pytest.fixture
def native_observation():
    return {
        "manager": "NativeServerManager",
        "runtime": "native",
        "running": True,
        "on_core_loop": True,
        "legacy_listener": False,
        "legacy_thread": False,
        "admin_token_present": False,
        "revision": "candidate",
        "library_version": "candidate-version",
        "core_version": "2026.8.0",
        "python_version": "3.14.2 (Core image interpreter)",
        "architecture": "aarch64",
    }


@pytest.mark.parametrize("field", ["revision", "library_version"])
def test_a_different_candidate_cannot_save_a_native_ready_receipt(
    monkeypatch, native_observation, tmp_path, field, candidate_config
):
    proof = {key: native_observation[key] for key in ("revision", "library_version")}
    (tmp_path / "native-build.json").write_text(json.dumps(proof))
    directory = tmp_path / "receipts"
    monkeypatch.setenv("E2E_ATTESTATION_DIRECTORY", str(directory))
    observed = {**native_observation, field: "different-candidate"}
    monkeypatch.setattr(
        "tests.src.e2e._conftest_native_runtime.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=Mock(), json=lambda: observed
        ),
    )
    with pytest.raises(AssertionError, match="staged candidate"):
        attest_native_runtime("http://fixture.test", {}, candidate_config)
    assert not directory.exists()


@pytest.mark.parametrize(
    "embedded,no_tools,native",
    [
        (False, False, False),
        (True, False, False),
        (True, True, False),
        (True, True, True),
    ],
)
def test_container_preparation_pairs_the_component_with_its_checkout_wheel(
    monkeypatch, tmp_path, embedded, no_tools, native
):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        container_harness.tempfile, "mkdtemp", lambda **_: str(tmp_path)
    )
    monkeypatch.setattr(container_harness.shutil, "copytree", lambda *_, **__: None)
    for name in (
        "_ensure_hacs_frontend",
        "_seed_legacy_yaml_backups",
        "_seed_non_yaml_package_file",
        "_seed_yaml_package_scene",
        "_refresh_recorder_timestamps",
        "_setup_config_permissions",
        "_install_embedded_server",
    ):
        monkeypatch.setattr(container_harness, name, lambda *_, **__: None)
    monkeypatch.setattr(container_harness, "_copy_local_blueprint_to_www", lambda _: {})
    monkeypatch.setattr(
        container_harness, "_is_no_tools_entry_selected", lambda: no_tools
    )
    monkeypatch.setattr(container_harness, "native_runtime_selected", lambda: native)

    def install(config, source, domain, title, **kwargs):
        if domain == "ha_mcp_tools":
            manifest = config / "custom_components/ha_mcp_tools/manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"requirements": ["ha-mcp==9.1.1", "other-lib"]})
            )
        return False

    def build(config):
        wheel = config / "ha_mcp-9.1.1-py3-none-any.whl"
        wheel.write_bytes(b"checkout-wheel")
        return wheel

    monkeypatch.setattr(container_harness, "_install_custom_component", install)
    monkeypatch.setattr(container_harness, "_build_embedded_server_wheel", build)

    def stage(_, config):
        wheel = build(config)
        manifest = config / "custom_components/ha_mcp_tools/manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "requirements": [
                        f"ha-mcp @ file:///config/{wheel.name}#sha256=fixture-digest",
                        "other-lib",
                    ]
                }
            )
        )
        return wheel

    monkeypatch.setattr(container_harness, "stage_native_runtime", stage)
    config, _, _, wheel = container_harness._prepare_testcontainer_config(embedded)
    manifest = json.loads(
        (config / "custom_components/ha_mcp_tools/manifest.json").read_text()
    )
    suffix = "#sha256=fixture-digest" if native else ""
    assert manifest["requirements"] == [
        f"ha-mcp @ file:///config/{wheel}{suffix}",
        "other-lib",
    ]


@pytest.mark.parametrize("observed_core", [None, "2026.10.3"])
def test_a_native_server_on_the_wrong_core_cannot_qualify_the_minimum(
    monkeypatch, observed_core, native_observation, tmp_path, candidate_config
):
    directory = tmp_path / "receipts"
    monkeypatch.setenv("E2E_ATTESTATION_DIRECTORY", str(directory))
    observed = {**native_observation, "core_version": observed_core}
    monkeypatch.setenv("E2E_EXPECTED_CORE_VERSION", "2026.8.0")
    monkeypatch.setattr(
        "tests.src.e2e._conftest_native_runtime.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=Mock(), json=lambda: observed
        ),
    )
    with pytest.raises(AssertionError, match="Core version"):
        attest_native_runtime("http://fixture.test", {}, candidate_config)
    assert not directory.exists()


def test_an_x64_container_cannot_qualify_the_arm64_lane(
    monkeypatch, native_observation, tmp_path, candidate_config
):
    directory = tmp_path / "receipts"
    monkeypatch.setenv("E2E_ATTESTATION_DIRECTORY", str(directory))
    monkeypatch.setenv("E2E_EXPECTED_ARCH", "ARM64")
    observed = {**native_observation, "architecture": "x86_64"}
    monkeypatch.setattr(
        "tests.src.e2e._conftest_native_runtime.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=Mock(), json=lambda: observed
        ),
    )
    with pytest.raises(AssertionError, match="architecture"):
        attest_native_runtime("http://fixture.test", {}, candidate_config)
    assert not directory.exists()


@pytest.fixture
def receipt_world(
    monkeypatch: pytest.MonkeyPatch, native_observation: dict[str, Any], tmp_path: Path
) -> Path:
    directory = tmp_path / "receipts"
    native_observation.update(
        owner_id="private-owner",
        token="private-token",
        endpoint="http://private-endpoint",
        private_config={"password": "private-password"},
    )
    monkeypatch.setenv("E2E_ATTESTATION_DIRECTORY", str(directory))
    monkeypatch.setenv("E2E_EXPECTED_CORE_VERSION", native_observation["core_version"])
    monkeypatch.setenv("E2E_EXPECTED_ARCH", native_observation["architecture"])
    monkeypatch.setattr(
        "tests.src.e2e._conftest_native_runtime.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            raise_for_status=Mock(), json=lambda: native_observation
        ),
    )
    return directory


def test_attested_workers_preserve_actual_runtime_values_without_private_data(
    monkeypatch: pytest.MonkeyPatch,
    native_observation: dict[str, Any],
    receipt_world: Path,
    candidate_config,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "public-source-revision")
    monkeypatch.setenv("GITHUB_RUN_ID", "public-run-id")
    monkeypatch.setenv("GITHUB_TOKEN", "private-github-token")
    for worker in ("gw0", "gw1", None):
        if worker is None:
            monkeypatch.delenv("PYTEST_XDIST_WORKER")
        else:
            monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
        assert (
            attest_native_runtime("http://private-endpoint", {}, candidate_config)
            is native_observation
        )
    receipts = list(receipt_world.glob("*.json"))
    assert len(receipts) == 3
    observed_fields = {
        "core_version",
        "python_version",
        "architecture",
        "runtime",
        "on_core_loop",
        "revision",
        "library_version",
    }
    workers = set()
    for path in receipts:
        raw = path.read_text()
        payload = json.loads(raw)
        assert set(payload) == observed_fields | {"worker", "github"}
        assert {key: payload[key] for key in observed_fields} == {
            key: native_observation[key] for key in observed_fields
        }
        assert payload["github"]["sha"] == "public-source-revision"
        assert payload["github"]["run_id"] == "public-run-id"
        assert "private-" not in raw
        workers.add(payload["worker"])
    assert workers == {"gw0", "gw1", "master"}


def test_attestation_worker_cannot_escape_its_explicit_output_directory(
    monkeypatch: pytest.MonkeyPatch, receipt_world: Path, candidate_config
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "../escape")
    with pytest.raises(ValueError, match="worker"):
        attest_native_runtime("http://fixture.test", {}, candidate_config)
    assert not receipt_world.exists()
    assert list(receipt_world.parent.rglob("*.json")) == [
        candidate_config / "native-build.json"
    ]


def test_attestation_cannot_save_a_receipt_without_the_actual_core_python(
    native_observation: dict[str, Any], receipt_world: Path, candidate_config
) -> None:
    native_observation.pop("python_version")
    with pytest.raises(AssertionError, match="python_version"):
        attest_native_runtime("http://fixture.test", {}, candidate_config)
    assert not receipt_world.exists()


@pytest.fixture
def candidate_config(tmp_path, native_observation):
    proof = {key: native_observation[key] for key in ("revision", "library_version")}
    (tmp_path / "native-build.json").write_text(json.dumps(proof))
    return tmp_path
