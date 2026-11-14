# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx>=0.28.1,<0.29", "requests>=2.32,<3", "pytest>=8,<10", "testcontainers>=4.13,<5", "PyJWT>=2.10,<3", "bcrypt>=4.3,<6"]
# ///

"""Qualify real Main -> package upgrade -> explicit Native -> restart paths.

Run on an isolated fork runner. Raw output is private; only report.json is public.
Application code is built from separate immutable checkouts and never overlaid.
"""

# ruff: noqa: E402 -- standalone script establishes its repository import path

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import signal
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPOSITORY), str(REPOSITORY / "tests/native")]

import httpx

from tests.native.protocol_comparison.evidence import write_json
from tests.native.protocol_comparison.launch import (
    LABEL,
    cleanup,
    command,
    constrain_container,
    private_environment,
    source_proof,
)
from tests.native.upgrade_paths.contracts import (
    PHASES,
    PROFILES,
    Profile,
    UpgradeFailure,
    report_passed,
)
from tests.native.upgrade_paths.exercise import choose_native, enroll_main, phase, ready
from tests.native.upgrade_paths.staging import (
    build_assets,
    entry_identity,
    install_candidate,
    prepare_imports,
    receipt,
    seed_profile,
)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def reclaim(directory: Path, image: str, nonce: str) -> None:
    """Core writes private storage as root; restore only this run's ownership."""
    if os.name == "nt":
        return
    program = (
        "import os; from pathlib import Path; root=Path('/upgrade'); "
        f"uid,gid={os.getuid()},{os.getgid()}; "
        "[os.chown(p,uid,gid,follow_symlinks=False) for p in [root,*root.rglob('*')]]"
    )
    command(
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--label",
        f"{LABEL}={nonce}",
        "--entrypoint",
        "python3",
        "--mount",
        f"type=bind,src={directory},dst=/upgrade",
        image,
        "-c",
        program,
    )


def stop(
    container: Any, config: Path, image: str, nonce: str, *, remove: bool = True
) -> None:
    wrapped = container.get_wrapped_container()
    wrapped.stop(timeout=45)
    wrapped.reload()
    state = wrapped.attrs["State"]
    if state["OOMKilled"] or state["ExitCode"] not in {0, 143}:
        raise UpgradeFailure("core_did_not_stop_cleanly")
    if remove:
        container.stop()
    reclaim(config, image, nonce)


def capture_setup(container: Any) -> None:
    """Observe actual completed manifest setup before any candidate restart."""
    from e2e._conftest_native_runtime import capture_native_dependencies

    capture_native_dependencies(container, "after_core_setup")


def start(
    config: Path,
    wheel: Path,
    image: str,
    nonce: str,
    name: str,
    network: str,
    ports: tuple[int, int],
    *,
    candidate: bool,
) -> Any:
    from e2e._conftest_testcontainer import build_ha_testcontainer

    os.environ["E2E_EMBEDDED_RUNTIME"] = "native" if candidate else "legacy"
    container = build_ha_testcontainer(config, True, wheel.name)
    constrain_container(container, network, name, nonce)
    container.ports = {
        "8123/tcp": ("127.0.0.1", ports[0]),
        "9584/tcp": ("127.0.0.1", ports[1]),
    }
    container.start()
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    actual = wrapped.attrs
    if actual["Image"] != image or actual["HostConfig"]["Privileged"]:
        raise UpgradeFailure("container_isolation_changed")
    for port, host in zip((8123, 9584), ports, strict=True):
        if actual["NetworkSettings"]["Ports"][f"{port}/tcp"] != [
            {"HostIp": "127.0.0.1", "HostPort": str(host)}
        ]:
            raise UpgradeFailure("client_endpoint_binding_changed")
    return container


async def profile_run(  # noqa: C901, PLR0915 -- keep the four ordered upgrade phases and their cleanup together
    args: argparse.Namespace,
    private: Path,
    profile: Profile,
    assets: tuple[Path, Path],
    image: str,
    nonce: str,
    result: dict[str, Any],
) -> None:
    directory = private / profile.name
    directory.mkdir()
    config = directory / "config"
    os.environ["E2E_EMBEDDED_RUNTIME"] = "legacy"
    actor, legacy = seed_profile(
        REPOSITORY, args.baseline_source, assets[0], config, profile
    )
    entry, _identity = entry_identity(config)
    ports = (free_port(), free_port())
    origin = f"http://127.0.0.1:{ports[0]}"
    url = (
        f"http://127.0.0.1:{ports[1]}" + entry["data"]["secret_path"]
        if profile.route == "direct"
        else origin + "/api/webhook/" + entry["data"]["webhook_id"]
    )
    path = directory / "client-connection.json"
    network = f"upgrade-{nonce}-{profile.name}"
    command("docker", "network", "create", "--label", f"{LABEL}={nonce}", network)
    container = None
    active_phase = "main"
    wheel = config / assets[0].name
    expected = receipt(
        args.baseline_source, args.baseline_revision, wheel, config, image, nonce
    )
    connection_hash, grant, baseline, catalogues = "", {}, None, {}
    try:
        for index, active_phase in enumerate(PHASES):
            async with httpx.AsyncClient(
                timeout=45, trust_env=False, follow_redirects=False
            ) as http:
                if active_phase == "upgraded":
                    wheel = install_candidate(REPOSITORY, assets[1], config)
                    expected = receipt(
                        args.candidate_source,
                        args.candidate_revision,
                        wheel,
                        config,
                        image,
                        nonce,
                    )
                if container is None:
                    container = start(
                        config,
                        wheel,
                        image,
                        nonce,
                        network + f"-{index}",
                        network,
                        ports,
                        candidate=index > 0,
                    )
                else:
                    # Core 2026.11 installs into the container's Python environment,
                    # not config/deps. Retain that installation for restart proofs.
                    container.get_wrapped_container().start()
                proof = await ready(
                    http,
                    origin,
                    actor["token"],
                    expected,
                    "legacy" if index < 2 else "native",
                )
                if index > 0:
                    await asyncio.to_thread(capture_setup, container)
                if active_phase == "main":
                    connection_hash, grant = await enroll_main(
                        http, origin, url, profile.auth, actor, legacy, path
                    )
                # Retain bounded, non-secret provenance rather than raw Core logs.
                result.setdefault("runtime", {})[active_phase] = {
                    k: proof[k]
                    for k in (
                        "revision",
                        "core_version",
                        "core_image_id",
                        "component_sha256",
                        "package_sha256",
                        "ha_mcp_version",
                        "private_versions",
                        "runtime",
                    )
                }
                observed, grant = await phase(
                    http,
                    path,
                    connection_hash,
                    grant,
                    proof,
                    baseline,
                    catalogues,
                    control=(origin, actor["token"]),
                )
                result["phases"][active_phase] = observed
                if baseline is None:
                    baseline = observed
                if active_phase == "upgraded":
                    await choose_native(
                        http,
                        origin,
                        actor["token"],
                        proof["entry_id"],
                        actor["user_id"],
                    )
                remove = active_phase in {"main", "restarted"}
                stop(container, config, image, nonce, remove=remove)
                if remove:
                    container = None
    except Exception as error:  # noqa: BLE001 -- never export arbitrary URLs, HTTP bodies or credentials
        category = (
            str(error) if isinstance(error, UpgradeFailure) else type(error).__name__
        )
        if not re.fullmatch(r"[A-Za-z_]{1,80}", category):
            category = "upgrade_failed"
        result["phases"][active_phase] = {"passed": False, "failure": category}
        if isinstance(error, UpgradeFailure) and error.diagnostic:
            result["phases"][active_phase]["diagnostic"] = error.diagnostic
    finally:
        if container is not None:
            try:
                stop(container, config, image, nonce)
            except Exception:  # noqa: BLE001 -- outer label-scoped cleanup is mandatory too
                result["cleanup_failed"] = True
        for name in PHASES:
            result["phases"].setdefault(
                name, {"passed": False, "failure": "prerequisite_failed"}
            )


async def run(args: argparse.Namespace) -> int:  # noqa: C901 -- one serial qualification with mandatory cleanup
    report: dict[str, Any] = {
        "cleanup_complete": False,
        "sources_verified": False,
        "baseline_revision": args.baseline_revision,
        "candidate_revision": args.candidate_revision,
        "baseline_repository": "homeassistant-ai/ha-mcp",
        "baseline_branch": args.baseline_branch,
        "profiles": [],
        "scope": "component embedded HTTP on one immutable Core image",
        "not_qualified": [
            "in-place library upgrade in Main's existing Python environment",
            "stdio",
            "external server",
            "Home Assistant app (add-on) upgrade on HAOS",
            "Cloudflare/Nabu Casa routing",
            "client vendor UI",
            "all tool semantics",
        ],
    }
    if await asyncio.to_thread(args.state.exists) or await asyncio.to_thread(
        args.output.exists
    ):
        raise ValueError("fresh_state_and_output_required")
    args.output.mkdir(parents=True)
    try:
        if (
            args.baseline_source.resolve() == args.candidate_source.resolve()
            or REPOSITORY
            in {args.baseline_source.resolve(), args.candidate_source.resolve()}
        ):
            raise ValueError("separate_immutable_source_checkouts_required")
        report["source_trees"] = {
            "baseline": source_proof(args.baseline_source, args.baseline_revision),
            "candidate": source_proof(args.candidate_source, args.candidate_revision),
        }
        host = json.loads(
            command(
                "docker",
                "context",
                "inspect",
                "--format",
                "{{json .Endpoints.docker.Host}}",
            )
        )
        if not host.startswith(("unix://", "npipe://")):
            raise ValueError("local_disposable_docker_required")
        command("docker", "pull", args.core_image, timeout=600)
        image = command(
            "docker", "image", "inspect", args.core_image, "--format", "{{.Id}}"
        )
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("immutable_core_image_required")
        os.environ["HA_TEST_IMAGE"] = image
        os.environ["E2E_EMBEDDED_RUNTIME"] = "legacy"
        prepare_imports(REPOSITORY)
        nonce = secrets.token_hex(16)
        temporary = await asyncio.to_thread(Path(tempfile.gettempdir()).resolve)
        private = temporary / ("ha-mcp-protocol-" + nonce)
        write_json(
            args.state, {"nonce": nonce, "private": str(private), "image": image}
        )
        await asyncio.to_thread(args.state.chmod, 0o600)
        private.mkdir(mode=0o700)
        os.environ["HA_E2E_PIP_CACHE"] = str(private / "pip-cache")
        assets = build_assets(args.baseline_source, args.candidate_source, private)
        for profile in PROFILES:
            result: dict[str, Any] = {"profile": profile.name, "phases": {}}
            report["profiles"].append(result)
            try:
                await profile_run(args, private, profile, assets, image, nonce, result)
            except Exception as error:  # noqa: BLE001 -- setup exceptions may contain secrets
                result["setup_failure_type"] = type(error).__name__
        for name, source in (
            ("baseline", args.baseline_source),
            ("candidate", args.candidate_source),
        ):
            revision = getattr(args, name + "_revision")
            if source_proof(source, revision) != report["source_trees"][name]:
                raise ValueError("source_changed_during_upgrade")
        report["sources_verified"] = True
    except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 -- public evidence excludes exception messages
        report["failure"] = type(error).__name__
    finally:
        try:
            report["cleanup_complete"] = cleanup(args.state)
        except Exception:  # noqa: BLE001 -- retain cleanup state for the Actions fallback
            report["cleanup_complete"] = False
        report["upgrade_passed"] = report_passed(report, require_native=False)
        report["native_switch_passed"] = report_passed(report, require_native=True)
        write_json(args.output / "report.json", report)
    return 0 if report["upgrade_passed"] and report["native_switch_passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "cleanup", "preflight"))
    parser.add_argument("--state", type=Path, required=True)
    for name in ("baseline-source", "candidate-source", "output"):
        parser.add_argument("--" + name, type=Path)
    for name in (
        "baseline-revision",
        "candidate-revision",
        "baseline-branch",
        "core-image",
    ):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    # Builders and Docker helpers inherit only the established disposable-run
    # allowlist, never household/proxy settings or Actions credentials.
    environment = private_environment()
    repository = os.environ.get("GITHUB_REPOSITORY")
    if repository is not None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            parser.error("invalid GitHub repository identity")
        environment["GITHUB_REPOSITORY"] = repository
    os.environ.clear()
    os.environ.update(environment)
    if args.command == "preflight":
        prepare_imports(REPOSITORY)
        print("Upgrade host imports verified; no application or SDK imported")
        return 0
    if args.command == "cleanup":
        return 0 if cleanup(args.state) else 1
    if any(
        getattr(args, name.replace("-", "_")) is None
        for name in (
            "baseline-source",
            "candidate-source",
            "output",
            "baseline-revision",
            "candidate-revision",
            "baseline-branch",
            "core-image",
        )
    ):
        parser.error(
            "run requires both immutable sources, baseline branch, Core image and output"
        )
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
