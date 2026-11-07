"""Feed the real GitHub-downloaded ZIP to the existing HA installation fixture."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

_original_run = subprocess.run
_replacements: list[dict[str, str]] = []


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def pytest_sessionstart(session: pytest.Session) -> None:
    subject = Path(os.environ["ZIP_PROOF_SUBJECT"]).resolve()
    archive = Path(os.environ["ZIP_PROOF_ARCHIVE"]).resolve()
    report = json.loads(Path(os.environ["ZIP_PROOF_REPORT"]).read_text())
    actual = _original_run(
        ["git", "rev-parse", "HEAD"],
        cwd=subject,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if (
        actual != report["subject_sha"]
        or not report["passed"]
        or report["cleanup_failures"]
    ):
        raise pytest.UsageError(
            "The downloaded artifact lacks a clean exact-head proof"
        )
    if _digest(archive) != report["digest"]:
        raise pytest.UsageError("The downloaded release artifact digest changed")

    def run_with_release(args: Any, *positional: Any, **kwargs: Any) -> Any:
        result = _original_run(args, *positional, **kwargs)
        if not isinstance(args, (list, tuple)) or len(args) < 4:
            return result
        if Path(str(args[1])).resolve() != subject / "scripts/build_component_zip.py":
            return result
        if "--output" not in args:
            return result
        if (
            "--component-dir" in args
            and Path(str(args[args.index("--component-dir") + 1])).resolve()
            != subject / "custom_components/ha_mcp_tools"
        ):
            return result
        output = Path(str(args[args.index("--output") + 1])).resolve()
        if not output.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise pytest.UsageError(
                "The fixture's ZIP output left the temporary directory"
            )
        with zipfile.ZipFile(output) as built, zipfile.ZipFile(archive) as downloaded:
            if set(built.namelist()) != set(downloaded.namelist()) or any(
                built.read(name) != downloaded.read(name) for name in built.namelist()
            ):
                raise pytest.UsageError(
                    "The real release ZIP differs from the subject builder"
                )
        shutil.copyfile(archive, output)
        context = os.environ.get("PYTEST_CURRENT_TEST", "")
        _replacements.append({"context": context, "digest": _digest(output)})
        return result

    subprocess.run = run_with_release


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    subprocess.run = _original_run
    receipt = Path(os.environ["ZIP_PROOF_RECEIPT"])
    receipt.write_text(json.dumps(_replacements, indent=2) + "\n", encoding="utf-8")
    if not any("component@working-tree" in value["context"] for value in _replacements):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
