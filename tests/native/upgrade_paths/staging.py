"""Install each revision's own component and wheel into one retained HA config."""

from __future__ import annotations

import base64
import json
import secrets
import shutil
from pathlib import Path
from typing import Any

from tests.native.protocol_comparison.evidence import build_receipt, write_json
from tests.native.protocol_comparison.launch import (
    command,
    configure_entry,
    seed_auth,
    store,
)
from tests.native.protocol_comparison.launcher_support import import_worker_helpers

from .contracts import Profile, fingerprint


def build_assets(baseline: Path, candidate: Path, private: Path) -> tuple[Path, Path]:
    from qualification_artifacts import build_candidate_artifacts

    output = private / "baseline-assets"
    output.mkdir()
    command(
        "uv", "build", "--wheel", "--out-dir", str(output), str(baseline), timeout=600
    )
    wheels = list(output.glob("ha_mcp-*.whl"))
    if len(wheels) != 1:
        raise ValueError("exactly_one_baseline_wheel_required")
    assets = build_candidate_artifacts(candidate, private / "candidate-assets")
    return wheels[0], assets


def seed_profile(
    harness: Path, source: Path, wheel: Path, config: Path, profile: Profile
) -> tuple[dict[str, str], dict[str, str]]:
    import bcrypt
    from e2e._conftest_embedded import _install_embedded_server
    from e2e._conftest_seed import _install_custom_component, pair_component_library

    config.mkdir()
    store(config, "core.config_entries", {"entries": []})
    actors = seed_auth(config)
    actor = actors[0]
    actor.update(username="upgrade-admin", password=secrets.token_urlsafe(32))
    auth_file = config / ".storage/auth"
    auth = json.loads(auth_file.read_bytes())
    auth["data"]["credentials"].append(
        {
            "id": secrets.token_hex(16),
            "user_id": actor["user_id"],
            "auth_provider_type": "homeassistant",
            "auth_provider_id": None,
            "data": {"username": actor["username"]},
        }
    )
    write_json(auth_file, auth)
    password = base64.b64encode(
        bcrypt.hashpw(actor["password"].encode(), bcrypt.gensalt())
    ).decode()
    store(
        config,
        "auth_provider.homeassistant",
        {"users": [{"username": actor["username"], "password": password}]},
    )
    (config / "configuration.yaml").write_text(
        "homeassistant:\n  name: Disposable upgrade qualification\n  latitude: 0\n"
        "  longitude: 0\n  elevation: 0\n  unit_system: metric\n  time_zone: UTC\n"
        "  auth_providers:\n    - type: homeassistant\n"
        "http:\napi:\nwebsocket_api:\nconfig:\nlogger:\n  default: warning\n"
        "input_boolean:\n  upgrade_probe:\n    name: Persisted upgrade witness\n"
        "protocol_fixture:\nupgrade_fixture:\n",
        encoding="utf-8",
    )
    _install_custom_component(
        config, source / "custom_components/ha_mcp_tools", "ha_mcp_tools", "HA-MCP"
    )
    shutil.copyfile(wheel, config / wheel.name)
    pair_component_library(config, wheel.name)
    _install_embedded_server(config, wheel.name)
    configure_entry(config, "legacy", actors)
    path = config / ".storage/core.config_entries"
    entries = json.loads(path.read_bytes())
    entry = next(
        e
        for e in entries["data"]["entries"]
        if e.get("data", {}).get("entry_type") == "server"
    )
    legacy = {
        "client_id": secrets.token_urlsafe(24),
        "client_secret": secrets.token_urlsafe(48),
    }
    entry["data"].update(
        oauth_client_id=legacy["client_id"],
        oauth_client_secret=legacy["client_secret"],
        oauth_signing_key=secrets.token_hex(32),
        dcr_signing_key=secrets.token_hex(32),
    )
    # Model a Main installation: neither a Native selector nor a pip override.
    entry["options"].pop("runtime_mode", None)
    entry["options"].pop("pip_spec", None)
    entry["options"].update(
        bind_host="0.0.0.0",
        server_port=9584,
        webhook_auth={
            "none": "none",
            "ha-bearer": "ha_auth",
            "ha-oauth": "ha_auth",
            "legacy-oauth": "legacy",
        }[profile.auth],
    )
    write_json(path, entries)
    shutil.copytree(
        harness / "tests/native/protocol_comparison/protocol_fixture",
        config / "custom_components/protocol_fixture",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        Path(__file__).with_name("fixture"),
        config / "custom_components/upgrade_fixture",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copyfile(
        Path(__file__).with_name("readiness.py"),
        config / "custom_components/upgrade_fixture/readiness.py",
    )
    return actor, legacy


def install_candidate(harness: Path, assets: Path, config: Path) -> Path:
    from e2e._conftest_native_runtime import stage_native_dependency_capture
    from qualification_artifacts import stage_candidate_component

    wheel = stage_candidate_component(
        assets, config / "custom_components/ha_mcp_tools", config
    )
    stage_native_dependency_capture(harness, config)
    return wheel


def receipt(
    source: Path, revision: str, wheel: Path, config: Path, image: str, nonce: str
) -> dict[str, Any]:
    expected = build_receipt(
        source, revision, config / "custom_components/ha_mcp_tools", wheel, image, nonce
    )
    write_json(config / "protocol-build.json", expected)
    return expected


def entry_identity(config: Path) -> tuple[dict[str, Any], str]:
    entries = json.loads((config / ".storage/core.config_entries").read_bytes())[
        "data"
    ]["entries"]
    entry = next(e for e in entries if e.get("data", {}).get("entry_type") == "server")
    keys = (
        "webhook_id",
        "secret_path",
        "oauth_client_id",
        "oauth_client_secret",
        "oauth_signing_key",
        "dcr_signing_key",
    )
    return entry, fingerprint(
        {
            "entry_ids": sorted(
                e["entry_id"] for e in entries if e["domain"] == "ha_mcp_tools"
            ),
            **{k: entry["data"].get(k) for k in keys},
        }
    )


def prepare_imports(harness: Path) -> None:
    import_worker_helpers(harness)
