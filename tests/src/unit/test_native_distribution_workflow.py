"""Qualification remains available upstream without publication authority."""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    "filename", ["native-distribution.yml", "native-continuity.yml", "haos-native.yml"]
)
def test_qualification_is_manual_or_branch_scoped_without_repository_lock(
    filename: str,
) -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load(
        (root / ".github/workflows" / filename).read_text(encoding="utf-8")
    )
    triggers = workflow[True]
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert "github.repository" not in job.get("if", "")


def test_profile_workflow_preserves_inputs_without_publish_authority() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / ".github/workflows/native-distribution.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(workflow[True]) == {"workflow_call", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["build"]
    assert "environment" not in job and "secrets" not in job
    steps = job["steps"]
    builder = next(step for step in steps if step.get("id") == "build")
    assert builder["env"]["RELEASE_VERSION"] == "${{ inputs.version }}"
    assert builder["env"]["RELEASE_TAG"] == "${{ inputs.tag }}"
    assert "inputs.source_revision" in builder["env"]["SOURCE_REF"]
    assert '--revision "$SOURCE_SHA"' in builder["run"]
    assert "--with-standalone --prepare-hacs" in builder["run"]
    assert "dev_version.sh" not in builder["run"]
    assert "semantic-release" not in builder["run"]
    assert "git push" not in builder["run"] and "gh release" not in builder["run"]
    assert "uv publish" not in builder["run"]
    assert not any("pypi-publish" in step.get("uses", "") for step in steps)
    upload = next(step for step in steps if "upload-artifact" in step.get("uses", ""))
    assert upload["with"]["path"] == "dist/native-distribution/"
    assert upload["with"]["if-no-files-found"] == "error"


def test_pull_request_performance_worker_receives_no_frontend_metadata_token() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load(
        (root / ".github/workflows/performance-tests.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["performance-tests"]["steps"]
    step = next(row for row in steps if row.get("id") == "perf_tests")
    assert (
        not {"GH_TOKEN", "GITHUB_TOKEN", "HACS_FRONTEND_GITHUB_TOKEN"}
        & step["env"].keys()
    )
    metadata = next(row for row in steps if row.get("id") == "hacs_frontend_metadata")
    checkout = next(
        row for row in steps if row.get("uses", "").startswith("actions/checkout@")
    )
    assert steps.index(metadata) < steps.index(checkout)
    assert metadata["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "gh api repos/hacs/frontend/releases/latest" in metadata["run"]
    assert "HACS_FRONTEND_RELEASE_TAG=" in metadata["run"]
    validation = metadata["run"].index('if [[ ! "$tag" =~')
    publication = metadata["run"].index("printf 'HACS_FRONTEND_RELEASE_TAG=")
    assert validation < publication
    assert "exit 1" in metadata["run"][validation:publication]
    assert "python" not in metadata["run"] and "uv run" not in metadata["run"]
