"""Shared build fixtures without Home Assistant stand-ins."""

import importlib.util
import io
import json
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def release_builder(monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/native_release.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("native_release_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module.core_window,
        "resolve_window",
        lambda: module.core_window.make_window(
            "2026.10.4", {"2026.10.0": "3.14.9", "2026.10.4": "3.14.9"}
        ),
    )
    return module


@pytest.fixture
def source(tmp_path, release_builder, monkeypatch):
    root = tmp_path / "source"
    component = root / "custom_components/ha_mcp_tools"
    component.mkdir(parents=True)
    (root / "pyproject.toml").write_text("""[project]
name = "ha-mcp"
version = "8.7.0"
dependencies = [
    "httpx>=0.27",
    "rich>=15",
]
[project.scripts]
ha-mcp = "ha_mcp:main"
""")
    (root / "hacs.json").write_text(
        json.dumps(
            {"name": "HA-MCP", "homeassistant": "2026.10.0", "render_readme": True}
        )
    )
    contract = root / "src/ha_mcp/component_contract.py"
    contract.parent.mkdir(parents=True)
    contract.write_text('MIN_COMPONENT_VERSION = "8.7.0"\n')
    (root / "LICENSE").write_text("fixture license\n")
    (root / "README.md").write_text("upstream readme\n")
    (component / "manifest.json").write_text(
        json.dumps(
            {
                "domain": "ha_mcp_tools",
                "name": "HA-MCP",
                "version": "8.7.0",
                "requirements": ["ha-mcp==8.7.0", "ruamel.yaml>=0.18"],
            }
        )
    )
    (component / "const.py").write_text(
        'COMPONENT_VERSION = "8.7.0"\nMIN_NATIVE_HOME_ASSISTANT_VERSION = "2026.10.0"\nMIN_EMBEDDED_HOME_ASSISTANT_VERSION = "2026.10.0"\n'
    )
    (component / "hacs.json").write_text(json.dumps({"homeassistant": "2026.10.0"}))
    (component / "__init__.py").write_text("# fixture component\n")
    monkeypatch.setattr(release_builder, "run", lambda *args, **kwargs: "a" * 40)

    def stage(repository, staging, revision):
        shutil.copytree(repository, staging, dirs_exist_ok=True)
        return {"src/ha_mcp/skills/vendor": "b" * 40}

    def wheel_build(args, *, cwd, **kwargs):
        output = Path(args[args.index("--out-dir") + 1])
        output.mkdir(parents=True, exist_ok=True)
        project = tomllib.loads((cwd / "pyproject.toml").read_text())["project"]
        version, name = project["version"], project["name"]
        basename = f"{name.replace('-', '_')}-{version}"
        dependencies = [f"Requires-Dist: {item}\n" for item in project["dependencies"]]
        dependencies.extend(
            f"Requires-Dist: {item}; extra == '{extra}'\n"
            for extra, requirements in project.get("optional-dependencies", {}).items()
            for item in requirements
        )
        with zipfile.ZipFile(output / f"{basename}-py3-none-any.whl", "w") as wheel:
            wheel.writestr("ha_mcp/__init__.py", "# fixture library\n")
            wheel.writestr(
                "ha_mcp/component_contract.py",
                (cwd / "src/ha_mcp/component_contract.py").read_text(),
            )
            wheel.writestr(
                f"{basename}.dist-info/METADATA",
                f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n"
                + "".join(dependencies),
            )
            wheel.writestr(
                f"{basename}.dist-info/WHEEL",
                "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )
            wheel.writestr(f"{basename}.dist-info/RECORD", "installer rewrites this\n")
            wheel.writestr(
                f"{basename}.dist-info/entry_points.txt",
                "[console_scripts]\n"
                + "\n".join(
                    f"{key} = {value}" for key, value in project["scripts"].items()
                ),
            )
        if "--wheel" not in args:
            with tarfile.open(output / f"{basename}.tar.gz", "w:gz") as archive:
                payload = (cwd / "pyproject.toml").read_bytes()
                member = tarfile.TarInfo(f"{basename}/pyproject.toml")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(release_builder, "stage_revision", stage)
    monkeypatch.setattr(release_builder.subprocess, "run", wheel_build)
    return root
