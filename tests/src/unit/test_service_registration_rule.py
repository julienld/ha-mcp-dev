"""The service registration guard distinguishes MCP tools from HA services."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "source,refused",
    [
        ("self.engine.register(code_tool)", False),
        ("services.async_register(DOMAIN, 'name', handler)", True),
        ("services.register(DOMAIN, 'name', handler)", True),
        (
            "services.register(domain=DOMAIN, service='name', service_func=handler)",
            True,
        ),
        ("services.register(**kwargs)", True),
        ("services.async_register(*args, **kwargs)", True),
        ("async_register_admin_service(hass, DOMAIN, 'name', handler)", False),
    ],
)
def test_service_guard_preserves_admin_registration(
    source: str,
    refused: bool,
    tmp_path: Path,
) -> None:
    sample = tmp_path / "custom_components" / "ha_mcp_tools" / "example.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(source + "\n", encoding="utf-8")
    rule = (
        Path(__file__).resolve().parents[3] / "rules" / "no-plain-service-register.yml"
    )
    executable = shutil.which("ast-grep")
    assert executable is not None
    result = subprocess.run(
        [
            executable,
            "scan",
            "--rule",
            str(rule),
            "--json=compact",
            str(sample.relative_to(tmp_path)),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    assert bool(json.loads(result.stdout)) is refused
