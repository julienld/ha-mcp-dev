"""Native startup imports the complete catalog in a fresh real-Core interpreter."""

import subprocess
import sys

import pytest


def test_complete_native_catalog_imports_with_installed_core() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import custom_components.ha_mcp_tools.native_catalog"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "module",
    ["ha_mcp.tools.renamed_tool_middleware", "ha_mcp.transforms.categorized_search"],
)
def test_shared_alias_imports_do_not_load_remote_transports(module: str) -> None:
    code = (
        "import homeassistant, importlib, sys; "
        f"importlib.import_module({module!r}); "
        "remote = [name for name in sys.modules if name == 'ha_mcp.client' or name.startswith('ha_mcp.client.') or name == 'ha_mcp.backends.remote']; "
        "assert not remote, remote"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
