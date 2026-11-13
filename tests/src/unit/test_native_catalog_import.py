"""Native startup imports the complete catalog in a fresh real-Core interpreter."""

import subprocess
import sys


def test_complete_native_catalog_imports_with_installed_core() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import custom_components.ha_mcp_tools.native_catalog"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
