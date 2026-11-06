"""Legacy qualification must prove restart continuity and never run Native."""

import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest
import yaml

from tests.native import minimal_install, minimal_qualification

from .test_native_minimal_qualification import core_image, minimal  # noqa: F401


def test_legacy_install_uses_the_paired_wheel_for_real_runtime_startup(
    minimal,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    restarts = Mock(return_value=[{"identity": "same-entry"}])
    monkeypatch.setattr(minimal_install, "legacy_restarts", restarts)
    minimal_install.install(tmp_path, tmp_path, minimal.output, runtime="legacy")
    minimal.probes.assert_not_awaited()
    restarts.assert_called_once()
    manifest = json.loads(
        (tmp_path / "config/custom_components/ha_mcp_tools/manifest.json").read_bytes()
    )
    paired = manifest["requirements"][1]
    assert paired == f"ha-mcp @ {minimal.wheel.resolve().as_uri()}"
    proof = json.loads(minimal.output.read_bytes())
    assert proof["complete"] and proof["runtime_manifest_local_wheel_substitution"]


def test_legacy_selection_survives_the_isolated_worker_boundary(core_image) -> None:  # noqa: F811
    minimal_qualification.qualify(
        Path("assets"),
        core_image.output.parent / "work",
        core_image.output,
        image_receipt=Path("image.json"),
        expected_core=core_image.core,
        expected_arch="amd64",
        python_source="Core image",
        runtime="legacy",
    )
    command = core_image.run.call_args_list[-1].args[0]
    assert command[command.index("--runtime") + 1] == "legacy"


@pytest.mark.parametrize("changed", [False, True])
def test_restart_rejects_changed_entry_identity_and_observes_each_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: bool
) -> None:
    calls = []

    def run(command, **kwargs):
        phase = command[command.index("--phase") + 1]
        calls.append(phase)
        receipt = Path(command[command.index("--output") + 1])
        receipt.write_text(json.dumps({"identity": phase if changed else "same"}))
        assert kwargs["timeout"] > 0
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(minimal_install.subprocess, "run", run)
    observe = Mock()
    args = (tmp_path / "config", tmp_path, tmp_path / "proof.json")
    if changed:
        with pytest.raises(RuntimeError, match="changed entry"):
            minimal_install.legacy_restarts(*args, observe=observe)
    else:
        results = minimal_install.legacy_restarts(*args, observe=observe)
        assert results[0]["identity"] == results[1]["identity"]
    assert calls == ["first_start", "full_restart"]
    assert [call.args[0] for call in observe.call_args_list] == [
        "legacy_first_start",
        "legacy_full_restart",
    ]


def test_failed_first_process_never_attempts_or_claims_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Mock(return_value=CompletedProcess([], 1, "", "fixture failure"))
    monkeypatch.setattr(minimal_install.subprocess, "run", run)
    observe = Mock()
    with pytest.raises(RuntimeError, match="first_start failed"):
        minimal_install.legacy_restarts(
            tmp_path, tmp_path, tmp_path / "proof.json", observe=observe
        )
    run.assert_called_once()
    observe.assert_not_called()


def test_old_core_lane_qualifies_both_architectures_with_legacy_not_native() -> None:
    workflow = Path(__file__).resolve().parents[3] / ".github/workflows/legacy-core.yml"
    data = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    contract = data["jobs"]["contract"]
    matrix = contract["strategy"]["matrix"]
    assert {"2026.8.0", "2026.9.0"} <= set(matrix["core"])
    assert set(matrix["arch"]) == {"amd64", "aarch64"}
    command = next(
        step["run"] for step in contract["steps"] if "--runtime" in step.get("run", "")
    )
    assert "--runtime legacy" in command
    assert "--entrypoint python" in command and '"$IMAGE_ID"' in command
