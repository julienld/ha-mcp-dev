"""Resolve native Bash for workflow tests on Windows and Linux."""

import os
import shutil
from pathlib import Path

import pytest


def bash_executable() -> str:
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parent.parent / "bin/bash.exe" if git else None
        if candidate is None or not candidate.is_file():
            pytest.skip("Native Git Bash unavailable for workflow-shell tests")
        return str(candidate)
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash unavailable for workflow-shell tests")
    return bash


def bash_fixture_environment(directory: Path, commands: Path) -> dict[str, str]:
    """Keep fake commands first and temporary writes inside the owned test root."""
    if os.name == "nt":
        git_root = Path(bash_executable()).parent.parent
        paths = [commands, git_root / "usr/bin", git_root / "mingw64/bin"]
    else:
        paths = [commands, Path("/usr/bin"), Path("/bin")]
    temporary = directory.resolve()
    return {
        **{
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR"}
        },
        "PATH": os.pathsep.join(str(path) for path in paths),
        "TMPDIR": temporary.as_posix(),
        "TEMP": str(temporary),
        "TMP": str(temporary),
    }
