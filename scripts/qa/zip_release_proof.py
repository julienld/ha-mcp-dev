# /// script
# requires-python = ">=3.13"
# dependencies = ["PyYAML==6.0.3", "packaging==26.3"]
# ///
"""Run explicitly requested GitHub release proofs in an owned QA namespace."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.parse
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import yaml

REPOSITORY = "julienld/ha-mcp-dev"
TRAILERS = "\n\nCodex-Session: 01a1ab9a-90da-7452-9bec-86e40464cba2\nT3-Thread: a79d9703-47c6-4084-a1d7-62b70915a8f2"
SUBJECTS = {
    "assets": "1a153e83d72496b8851ad22485bafe01d4beeda7",
    "activation": "592116f9edb1858152c83796f1f6b10b5d1ed901",
}


def checked_context(environment: dict[str, str], variant: str) -> str:
    """Reject normal branches, other repositories and non-manual execution."""
    required = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "RUNNER_OS": "Linux",
    }
    if any(environment.get(key) != value for key, value in required.items()):
        raise ValueError("The proof requires the owned fork's manual Linux runner")
    if variant not in SUBJECTS or not environment.get("GH_TOKEN"):
        raise ValueError("A registered subject and job-scoped token are required")
    if not environment.get("GITHUB_REF", "").startswith(
        "refs/heads/qualify/zip-release-proof-"
    ):
        raise ValueError("Only the isolated proof branch may publish QA assets")
    run, attempt = (
        environment.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
    )
    if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in (run, attempt)):
        raise ValueError("Numeric workflow run and attempt IDs are required")
    return f"qa-zip-{run}-{attempt}-{variant}"


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=check,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


class Proof:
    def __init__(self, subject: Path, output: Path, variant: str) -> None:
        self.prefix = checked_context(dict(os.environ), variant)
        self.subject, self.output = subject.resolve(), output.resolve()
        self.variant, self.sha = variant, SUBJECTS[variant]
        if not self.output.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve()):
            raise ValueError("Proof files must stay inside RUNNER_TEMP")
        if (
            run(["git", "rev-parse", "HEAD"], cwd=self.subject).stdout.strip()
            != self.sha
        ):
            raise ValueError(
                "Subject checkout differs from its registered immutable SHA"
            )
        self.state_path = self.output / "state.json"
        self.state: dict[str, Any] = {
            "repository": REPOSITORY,
            "prefix": self.prefix,
            "variant": variant,
            "subject_sha": self.sha,
            "tags": {},
            "release_ids": [],
            "events": [],
            "passed": False,
        }
        self.owned_objects = {self.sha}
        self.output.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        write_json(self.state_path, self.state)

    def event(self, name: str, **fields: Any) -> None:
        self.state["events"].append({"name": name, **fields})
        self.save()

    def tag(self, role: str) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", role):
            raise ValueError("Invalid QA role")
        return f"{self.prefix}-{role}-dev.1"

    def owned_tag(self, value: str) -> bool:
        return value.startswith(self.prefix + "-") and "/" not in value

    def api(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        fields: dict | None = None,
        paginate: bool = False,
        optional: bool = False,
    ) -> Any:
        root = f"repos/{REPOSITORY}/"
        if endpoint != root.rstrip("/") and not endpoint.startswith(root):
            raise ValueError("API traffic must stay in the owned fork")
        if method != "GET":
            self.check_write(endpoint.removeprefix(root), method, fields or {})
        command = ["gh", "api", "--method", method, endpoint]
        if fields is not None:
            command += ["--input", "-"]
        if paginate:
            command += ["--paginate", "--slurp"]
        result = run(
            command,
            check=False,
            input_text=json.dumps(fields) if fields is not None else None,
        )
        if result.returncode:
            if optional and method == "GET" and "HTTP 404" in result.stderr:
                return None
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def check_write(self, path: str, method: str, fields: dict) -> None:  # noqa: C901 - all mutation allowlists are audited together
        if method == "POST" and path == "git/refs":
            ref = fields.get("ref", "")
            if (
                ref.startswith("refs/tags/")
                and self.owned_tag(ref[10:])
                and fields.get("sha") in self.owned_objects
            ):
                return
        if (
            method == "POST"
            and path == "git/tags"
            and self.owned_tag(fields.get("tag", ""))
        ):
            if (
                fields.get("object") in self.owned_objects
                and fields.get("type") == "commit"
            ):
                return
        if method == "POST" and path == "git/commits":
            if (
                fields.get("tree") == self.state.get("subject_tree")
                and fields.get("parents")
                and all(p in self.owned_objects for p in fields["parents"])
            ):
                return
        if method in {"PATCH", "DELETE"} and path.startswith("git/refs/tags/"):
            tag = urllib.parse.unquote(path.removeprefix("git/refs/tags/"))
            if self.owned_tag(tag) and tag in self.state["tags"]:
                if method == "DELETE" or fields.get("sha") in self.owned_objects:
                    return
        if method in {"PATCH", "DELETE"} and re.fullmatch(r"releases/[0-9]+", path):
            if int(path.rsplit("/", 1)[1]) in self.state["release_ids"]:
                if method == "DELETE" or fields == {
                    "draft": False,
                    "make_latest": "false",
                }:
                    return
        raise ValueError(f"Refusing out-of-namespace mutation: {method} {path}")

    def snapshot(self) -> dict:
        values: dict[str, Any] = {}
        for ref in ("heads/master", "tags/stable", "tags/latest"):
            value = self.api(
                f"repos/{REPOSITORY}/git/ref/{ref}", optional=ref != "heads/master"
            )
            values[ref] = value["object"]["sha"] if value else None
        latest = self.api(f"repos/{REPOSITORY}/releases/latest", optional=True)
        values["latest_release_id"] = latest["id"] if latest else None
        return values

    def git(
        self, checkout: Path, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess:
        return run(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
                *arguments,
            ],
            check=check,
        )

    def make_ref(self, tag: str, target: str) -> None:
        if not self.owned_tag(tag):
            raise ValueError("Ref must belong to this proof")
        self.state["tags"][tag] = target
        self.save()
        self.api(
            f"repos/{REPOSITORY}/git/refs",
            method="POST",
            fields={"ref": "refs/tags/" + tag, "sha": target},
        )

    def release(self, tag: str, *, optional: bool = False) -> dict | None:
        result = run(
            [
                "gh",
                "release",
                "view",
                tag,
                "--repo",
                REPOSITORY,
                "--json",
                "databaseId",
                "--jq",
                ".databaseId",
            ],
            check=False,
        )
        if result.returncode:
            if optional and "release not found" in result.stderr.lower():
                return None
            raise RuntimeError(result.stderr)
        value = self.api(f"repos/{REPOSITORY}/releases/{result.stdout.strip()}")
        if value["tag_name"] != tag or not self.owned_tag(tag):
            raise ValueError("Release identity leaves the proof namespace")
        if value["id"] not in self.state["release_ids"]:
            self.state["release_ids"].append(value["id"])
            self.save()
        return value

    def create_release(
        self,
        tag: str,
        archive: Path | None,
        *,
        draft: bool = False,
        prerelease: bool = True,
    ) -> dict:
        if not self.owned_tag(tag) or tag not in self.state["tags"]:
            raise ValueError("Create requires a pre-registered QA tag")
        args = ["gh", "release", "create", tag]
        if archive is not None:
            args += [str(archive)]
        args += [
            "--repo",
            REPOSITORY,
            "--latest=false",
            "--title",
            "QA ONLY: " + tag,
            "--notes",
            "Temporary isolated ZIP release proof; not a distribution channel.",
        ]
        if draft:
            args += ["--draft"]
        if prerelease:
            args += ["--prerelease"]
        run(args)
        value = self.release(tag)
        assert value is not None
        return value

    def asset(self, tag: str) -> dict:
        for _ in range(20):
            value = self.release(tag)
            assert value is not None
            found = next(
                (a for a in value["assets"] if a["name"] == "ha_mcp_tools.zip"), {}
            )
            if (
                found.get("state") == "uploaded"
                and found.get("digest")
                and found.get("size")
            ):
                return found
            time.sleep(1)
        raise TimeoutError("Uploaded QA asset never acquired its digest")

    def step(
        self,
        workflow: str,
        job: str,
        name: str,
        *,
        cwd: Path,
        environment: dict[str, str],
        mirror: Path | None = None,
        succeeds: bool = True,
    ) -> subprocess.CompletedProcess:
        data = yaml.safe_load((self.subject / workflow).read_text(encoding="utf-8"))
        text = next(
            s["run"] for s in data["jobs"][job]["steps"] if s.get("name") == name
        )
        if mirror:
            if not mirror.resolve().is_relative_to(self.output):
                raise ValueError("Snapshot writes must stay inside the proof output")
            text = text.replace("/tmp/mirror", str(mirror))
        result = run(
            ["bash", "-e", "-c", text],
            cwd=cwd,
            env={**os.environ, **environment},
            check=False,
        )
        if (result.returncode == 0) != succeeds:
            raise RuntimeError(name + "\n" + result.stdout + result.stderr)
        self.event(name, successful=succeeds, returncode=result.returncode)
        return result

    def stage(self, role: str, source_tag: str) -> tuple[Path, str]:
        mirror, tag = self.output / role, self.tag(role)
        mirror.mkdir()
        self.git(mirror, "init", "-q")
        self.git(mirror, "config", "user.name", "github-actions[bot]")
        self.git(
            mirror,
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        )
        self.git(
            mirror, "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git"
        )
        self.git(mirror, "config", "credential.helper", "!gh auth git-credential")
        environment = {
            "SOURCE_REPOSITORY": REPOSITORY,
            "VER": self.version,
            "PIN": self.version,
            "DIST": "ha-mcp",
            "SRC": str(self.subject),
            "CHANNEL": "stable",
            "TAG": tag,
            "GITHUB_ENV": str(self.output / "step.env"),
        }
        self.step(
            ".github/workflows/sync-integration-mirror.yml",
            "sync",
            "Stage snapshot",
            cwd=self.subject,
            environment=environment,
            mirror=mirror,
        )
        marker = mirror / ".github/component-zip-source.json"
        metadata = json.loads(marker.read_text())
        metadata["tag"] = source_tag  # Physical QA tag, same subject/stamped bytes.
        write_json(marker, metadata)
        # GITHUB_TOKEN cannot deploy workflow files. Their deployment-key path
        # is outside this proof; execute the subject's release steps directly.
        self.git(mirror, "add", "-A", "--", ".", ":(exclude).github/workflows")
        self.git(mirror, "commit", "-qm", "QA stamped component snapshot" + TRAILERS)
        self.step(
            ".github/workflows/sync-integration-mirror.yml",
            "sync",
            "Wait for the upstream integration ZIP before tagging",
            cwd=self.subject,
            environment=environment,
            mirror=mirror,
        )
        message = self.git(mirror, "log", "-1", "--format=%B").stdout.rstrip()
        if "Codex-Session:" not in message:
            self.git(mirror, "commit", "--amend", "-qm", message + TRAILERS)
        pinned = json.loads(marker.read_text())["digest"]
        if pinned != self.digest:
            raise ValueError("Snapshot pin differs from the qualified ZIP")
        commit = self.git(mirror, "rev-parse", "HEAD").stdout.strip()
        self.owned_objects.add(commit)
        self.state["tags"][tag] = commit
        self.save()
        self.git(
            mirror,
            "push",
            "--",
            f"https://github.com/{REPOSITORY}.git",
            f"HEAD:refs/tags/{tag}",
        )
        return mirror, tag

    def mirror_release(self, mirror: Path, tag: str, *, succeeds: bool = True) -> None:
        Path("/tmp/notes.md").write_text("Isolated QA ZIP proof.\n", encoding="utf-8")
        environment = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REF_NAME": tag}
        workflow = ".github/integration-mirror-workflows/release-on-tag.yml"
        self.step(
            workflow,
            "release",
            "Copy the upstream integration ZIP",
            cwd=mirror,
            environment=environment,
            succeeds=succeeds,
        )
        if succeeds:
            self.step(
                workflow,
                "release",
                "Create release for tag",
                cwd=mirror,
                environment=environment,
            )
            self.release(tag)

    def remove_release(self, tag: str) -> None:
        release = self.release(tag, optional=True)
        if release:
            self.api(f"repos/{REPOSITORY}/releases/{release['id']}", method="DELETE")

    def exercise_assets(self) -> None:
        archive = self.output / "built/ha_mcp_tools.zip"
        run(
            [
                sys.executable,
                str(self.subject / "scripts/build_component_zip.py"),
                "--output",
                str(archive),
            ],
            cwd=self.subject,
        )
        self.archive, self.digest = archive, sha256(archive)
        component = json.loads(
            (self.subject / "custom_components/ha_mcp_tools/manifest.json").read_text()
        )
        self.version = component["version"]
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.version):
            raise ValueError("The subject needs its paired released server version")
        source_tag = self.tag("source")
        self.make_ref(source_tag, self.sha)
        self.create_release(source_tag, archive)
        assert self.asset(source_tag)["digest"] == self.digest
        first, first_tag = self.stage("mirror-new", source_tag)
        self.mirror_release(first, first_tag)
        first_asset = self.asset(first_tag)
        run(
            [
                "gh",
                "release",
                "download",
                first_tag,
                "--repo",
                REPOSITORY,
                "--pattern",
                "ha_mcp_tools.zip",
                "--dir",
                str(self.output),
                "--clobber",
            ]
        )
        assert sha256(self.output / "ha_mcp_tools.zip") == self.digest
        first_asset = self.asset(first_tag)
        self.event(
            "download count observed",
            asset_id=first_asset["id"],
            download_count=first_asset["download_count"],
        )
        self.mirror_release(first, first_tag)
        assert self.asset(first_tag)["id"] == first_asset["id"]

        empty, empty_tag = self.stage("mirror-empty", source_tag)
        self.create_release(empty_tag, None, draft=True)
        draft_lookup = self.api(
            f"repos/{REPOSITORY}/releases/tags/{empty_tag}", optional=True
        )
        self.event(
            "draft lookup",
            tag_endpoint_visible=draft_lookup is not None,
            database_id=self.release(empty_tag)["id"],
        )
        self.mirror_release(empty, empty_tag)
        assert self.release(empty_tag)["draft"] is False

        complete, complete_tag = self.stage("mirror-complete", source_tag)
        self.create_release(complete_tag, archive, draft=True)
        preserved = self.asset(complete_tag)
        pinned, pinned_tag = self.stage("mirror-pinned", source_tag)
        bad = self.output / "replaced/ha_mcp_tools.zip"
        bad.parent.mkdir()
        shutil.copyfile(archive, bad)
        with zipfile.ZipFile(bad, "a") as target:
            target.writestr("unexpected.txt", "Not the tagged snapshot")
        run(
            [
                "gh",
                "release",
                "upload",
                source_tag,
                str(bad),
                "--repo",
                REPOSITORY,
                "--clobber",
            ]
        )
        assert self.asset(source_tag)["digest"] != self.digest
        self.mirror_release(pinned, pinned_tag, succeeds=False)
        assert self.release(pinned_tag, optional=True) is None
        self.mirror_release(first, first_tag)
        retained = self.asset(first_tag)
        assert retained["id"] == first_asset["id"]
        assert retained["download_count"] >= first_asset["download_count"]
        self.remove_release(source_tag)
        self.api(f"repos/{REPOSITORY}/git/refs/tags/{source_tag}", method="DELETE")
        self.mirror_release(complete, complete_tag)
        assert self.asset(complete_tag)["id"] == preserved["id"]
        assert self.release(complete_tag)["draft"] is False
        self.event(
            "asset qualification",
            digest=self.digest,
            mirror_asset_id=first_asset["id"],
            preserved_download_count=retained["download_count"],
            bytes=archive.stat().st_size,
        )

    def target_commit(self, parent: str) -> str:
        result = self.api(
            f"repos/{REPOSITORY}/git/commits",
            method="POST",
            fields={
                "message": "QA only: identical subject tree for ancestry proof"
                + TRAILERS,
                "tree": self.state["subject_tree"],
                "parents": [parent],
            },
        )
        self.owned_objects.add(result["sha"])
        return result["sha"]

    def annotated_ref(self, role: str, commit: str) -> tuple[str, str]:
        tag = self.tag(role)
        result = self.api(
            f"repos/{REPOSITORY}/git/tags",
            method="POST",
            fields={
                "tag": tag,
                "message": "QA only: annotated object lease proof",
                "object": commit,
                "type": "commit",
            },
        )
        self.owned_objects.add(result["sha"])
        self.make_ref(tag, result["sha"])
        self.git(
            self.subject,
            "fetch",
            "--no-tags",
            f"https://github.com/{REPOSITORY}.git",
            f"refs/tags/{tag}",
        )
        return tag, result["sha"]

    def exercise_finalizer(self) -> None:  # noqa: C901, PLR0915 - sequential live recovery scenario
        spec = importlib.util.spec_from_file_location(
            "qa_subject_finalizer", self.subject / "scripts/finalize_github_release.py"
        )
        assert spec and spec.loader
        finalizer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(finalizer)
        project = tomllib.loads((self.subject / "pyproject.toml").read_text())[
            "project"
        ]
        hacs = json.loads((self.subject / "hacs.json").read_text())
        component = json.loads(
            (self.subject / "custom_components/ha_mcp_tools/manifest.json").read_text()
        )
        assert hacs["zip_release"]
        logical_tag, alias = "v" + self.version, self.tag("stable-alias")
        _, old = self.annotated_ref("old-object", self.sha)
        self.make_ref(alias, old)
        first_commit = self.target_commit(self.sha)
        first_tag, first_object = self.annotated_ref("finalized-first", first_commit)
        second_commit = self.target_commit(first_commit)
        second_tag, second_object = self.annotated_ref(
            "finalized-second", second_commit
        )
        _, raced_object = self.annotated_ref("raced-object", second_commit)
        for tag in (first_tag, second_tag):
            self.create_release(tag, self.archive, draft=True, prerelease=False)
        invalid_tag, _ = self.annotated_ref("finalized-invalid", first_commit)
        self.create_release(
            invalid_tag,
            self.output / "replaced/ha_mcp_tools.zip",
            draft=True,
            prerelease=False,
        )
        selected, race = first_tag, False
        actual_push = finalizer._push_stable_ref

        def api(endpoint: str, **kwargs: Any) -> Any:
            method, fields = kwargs.get("method", "GET"), kwargs.get("fields")
            if endpoint.endswith("/releases?per_page=100"):
                pages = self.api(endpoint, paginate=True)
                return [
                    [
                        {**r, "tag_name": logical_tag}
                        for page in pages
                        for r in page
                        if r["tag_name"] == selected
                    ]
                ]
            endpoint = endpoint.replace(
                "/git/ref/tags/" + logical_tag, "/git/ref/tags/" + selected
            )
            if endpoint.endswith("/git/matching-refs/tags/stable"):
                values = self.api(endpoint.removesuffix("stable") + alias)
                return [
                    {**r, "ref": "refs/tags/stable"}
                    for r in values
                    if r["ref"] == "refs/tags/" + alias
                ]
            if method == "PATCH":
                assert endpoint.endswith(
                    "/releases/" + str(self.release(selected)["id"])
                )
                assert fields == {"draft": False}
                self.event("finalizer publishes", tag=selected)
                return self.api(
                    endpoint,
                    method="PATCH",
                    fields={"draft": False, "make_latest": "false"},
                )
            assert method == "GET"
            return self.api(endpoint)

        def push(remote: str, checkout: Path, target: str, expected: str) -> None:
            assert (
                remote == f"https://github.com/{REPOSITORY}.git"
                and checkout == self.subject
            )
            assert self.release(selected)["draft"] is False, (
                "Alias moved before publication"
            )
            if race:
                self.api(
                    f"repos/{REPOSITORY}/git/refs/tags/{alias}",
                    method="PATCH",
                    fields={"sha": raced_object, "force": True},
                )

            def namespaced_git(
                command: list[str], **options: Any
            ) -> subprocess.CompletedProcess:
                assert command[-1] == f"{target}:refs/tags/stable"
                assert f"--force-with-lease=refs/tags/stable:{expected}" in command
                return subprocess.run(
                    [
                        part.replace("refs/tags/stable", "refs/tags/" + alias)
                        for part in command
                    ],
                    check=options.pop("check"),
                    **options,
                )

            with patch.object(
                finalizer, "subprocess", SimpleNamespace(run=namespaced_git)
            ):
                actual_push(remote, checkout, target, expected)
            self.event("finalizer alias CAS", target=target, expected=expected)

        def finalize() -> dict:
            with (
                patch.object(finalizer, "_gh_json", api),
                patch.object(finalizer, "_push_stable_ref", push),
            ):
                return finalizer.finalize_release(
                    REPOSITORY,
                    logical_tag,
                    hacs,
                    component,
                    project=project,
                    checkout=self.subject,
                    attempts=3,
                    delay=2,
                )

        selected = invalid_tag
        try:
            finalize()
        except ValueError as error:
            assert "ZIP" in str(error)
        else:
            raise AssertionError("An uploaded ZIP with wrong members was published")
        assert self.release(selected)["draft"] is True
        assert (
            self.api(f"repos/{REPOSITORY}/git/ref/tags/{alias}")["object"]["sha"] == old
        )
        self.event("invalid uploaded ZIP rejected before writes", tag=selected)
        selected = first_tag
        assert finalize()["stable_ref_updated"]
        assert (
            self.api(f"repos/{REPOSITORY}/git/ref/tags/{alias}")["object"]["sha"]
            == first_object
        )
        assert not finalize()["stable_ref_updated"]
        selected, race = second_tag, True
        try:
            finalize()
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError(
                "A concurrent alias update did not reject the old lease"
            )
        assert self.release(selected)["draft"] is False
        assert (
            self.api(f"repos/{REPOSITORY}/git/ref/tags/{alias}")["object"]["sha"]
            == raced_object
        )
        race = False
        assert finalize()["stable_ref_updated"]
        assert (
            self.api(f"repos/{REPOSITORY}/git/ref/tags/{alias}")["object"]["sha"]
            == second_object
        )
        selected = first_tag
        try:
            finalize()
        except ValueError as error:
            assert "advance stable" in str(error)
        else:
            raise AssertionError("An old finalizer retry moved the alias backwards")
        self.event(
            "finalizer qualification",
            physical_alias=alias,
            logical_version=logical_tag,
            namespace_adapter="tag/ref labels; make_latest=false; namespaced Git CAS",
        )

    def execute(self) -> None:
        repository = self.api(f"repos/{REPOSITORY}")
        assert (
            repository["fork"]
            and repository["parent"]["full_name"] == "homeassistant-ai/ha-mcp"
        )
        assert repository["default_branch"] == "master"
        self.state["baseline"] = self.snapshot()
        self.state["subject_tree"] = self.api(
            f"repos/{REPOSITORY}/git/commits/{self.sha}"
        )["tree"]["sha"]
        self.save()
        self.exercise_assets()
        if self.variant == "activation":
            self.exercise_finalizer()
        assert self.snapshot() == self.state["baseline"], (
            "A protected fork ref or latest release changed"
        )
        self.state.update(passed=True, digest=self.digest)
        self.save()
        write_json(self.output / "report.json", self.state)

    def cleanup(self) -> None:
        if not self.state_path.exists():
            return
        self.state = json.loads(self.state_path.read_text())
        assert (
            self.state["prefix"] == self.prefix
            and self.state["subject_sha"] == self.sha
        )
        failures = []
        for tag in self.state["tags"]:
            try:
                self.remove_release(tag)
                ref = self.api(f"repos/{REPOSITORY}/git/ref/tags/{tag}", optional=True)
                if ref:
                    self.api(f"repos/{REPOSITORY}/git/refs/tags/{tag}", method="DELETE")
            except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
                failures.append({"tag": tag, "error": str(error)})
        self.state["cleanup_failures"] = failures
        if "baseline" in self.state:
            assert self.snapshot() == self.state["baseline"], (
                "Protected fork state differs after cleanup"
            )
        self.save()
        write_json(self.output / "report.json", self.state)
        if failures:
            raise RuntimeError("Some owned QA artifacts could not be cleaned up")


def report_workflow(variant: str) -> None:
    checked_context(dict(os.environ), variant)
    sha = SUBJECTS[variant]
    number = 12 if variant == "assets" else 13
    passed = all(
        os.environ.get(key) == "success" for key in ("PROOF_RESULT", "HA_RESULT")
    )
    url = f"https://github.com/{REPOSITORY}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    status = "success" if passed else "failure"
    run(
        ["gh", "api", f"repos/{REPOSITORY}/statuses/{sha}", "--input", "-"],
        input_text=json.dumps(
            {
                "state": status,
                "context": "ZIP release + HA / " + variant,
                "description": "Live GitHub release recovery and HA ZIP installation: "
                + status,
                "target_url": url,
            }
        ),
    )
    head = json.loads(run(["gh", "api", f"repos/{REPOSITORY}/pulls/{number}"]).stdout)[
        "head"
    ]["sha"]
    body = (
        f"[Agent] Live ZIP qualification: **{status}**. Tested `{sha}`"
        + (" (the PR head has since changed)" if head != sha else "")
        + f". [Run and evidence]({url}).\n\n"
        + f"GitHub sandbox: {os.environ.get('PROOF_RESULT')}; existing HA install/update scenarios: {os.environ.get('HA_RESULT')}.\n\n"
        + "The sandbox uses temporary QA tags/releases in this fork and cleans them afterwards. "
        + "Production stable/latest refs, publisher enablement, workflow deployment keys and HACS/Marketplace selection are not qualified by this run."
    )
    run(
        ["gh", "api", f"repos/{REPOSITORY}/issues/{number}/comments", "--input", "-"],
        input_text=json.dumps({"body": body}),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=SUBJECTS, required=True)
    parser.add_argument("--subject", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.report:
        report_workflow(args.variant)
        return
    if args.subject is None or args.output is None:
        parser.error("--subject and --output are required for live proof and cleanup")
    proof = Proof(args.subject, args.output, args.variant)
    try:
        if args.cleanup:
            proof.cleanup()
        else:
            proof.execute()
    except Exception as error:  # noqa: BLE001 - redact credentials from every retained failure
        token = os.environ.get("GH_TOKEN", "")
        details = "\n".join(
            str(value)
            for value in (
                error,
                getattr(error, "stderr", ""),
                getattr(error, "stdout", ""),
            )
            if value
        )
        message = details.replace(token, "[REDACTED]") if token else details
        write_json(args.output / "failure.json", {"error": message})
        raise RuntimeError(message) from None


if __name__ == "__main__":
    main()
