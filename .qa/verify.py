# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Assert real QA release handoffs and report them on the single preparation PR."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

SOURCE = "julienld/ha-mcp-simple-release-qa-20261108"
MIRROR = "julienld/ha-mcp-simple-mirror-qa-20261108"
FORK = "julienld/ha-mcp-dev"
INDEX = "https://julienld.github.io/ha-mcp-simple-mirror-qa-20261108"
SITE = "https://julienld.github.io/ha-mcp-simple-release-qa-20261108"


def api(repo: str, path: str, fields: dict | None = None) -> object:
    if repo not in {SOURCE, MIRROR, FORK} or (fields is not None and repo != FORK):
        raise ValueError("Unexpected QA endpoint or cross-repository write")
    args = ["gh", "api", f"repos/{repo}" + ("/" + path if path else "")]
    if fields is not None:
        args += ["--input", "-"]
    result = subprocess.run(
        args,
        input=json.dumps(fields) if fields is not None else None,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        if fields is None and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else None


def download(url: str) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "github.com",
        "julienld.github.io",
    }:
        raise ValueError("Unexpected public QA download origin")
    request = urllib.request.Request(
        url, headers={"User-Agent": "ha-mcp-simple-zip-qa"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def contents(repo: str, path: str, ref: str) -> dict:
    value = api(repo, f"contents/{path}?ref={urllib.parse.quote(ref, safe='')}")
    if not isinstance(value, dict) or value.get("encoding") != "base64":
        raise ValueError("QA source metadata is unavailable")
    return json.loads(base64.b64decode(value["content"]))


def receipt(release: dict, workflow: str, parent: int | None = None) -> dict | None:
    assets = [
        a
        for a in release["assets"]
        if a["name"].startswith("qa-receipt-") and a["state"] == "uploaded"
    ]
    for asset in reversed(assets):
        value = json.loads(download(asset["browser_download_url"]))
        if value["workflow"] == workflow and (
            parent is None or value["parent"]["id"] == parent
        ):
            return value
    return None


def release(repo: str, tag: str) -> dict | None:
    value = api(repo, "releases/tags/" + urllib.parse.quote(tag, safe=""))
    if not isinstance(value, dict) or value.get("draft"):
        return None
    return value


def asset(release_data: dict) -> dict | None:
    return next(
        (
            a
            for a in release_data["assets"]
            if a["name"] == "ha_mcp_tools.zip"
            and a["state"] == "uploaded"
            and a["size"] > 0
        ),
        None,
    )


def verify_once(phase: str, product: str, producer: str) -> dict | None:
    candidates = api(SOURCE, "releases?per_page=30")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        tag = candidate["tag_name"]
        is_dev = bool(re.fullmatch(r"v\d+\.\d+\.\d+\.dev\d+", tag))
        if candidate["draft"] or is_dev != (phase == "dev"):
            continue
        upstream = asset(candidate)
        if upstream is None:
            continue
        origin = contents(SOURCE, ".qa/product-origin.json", tag)
        if origin.get("product_sha") != product:
            continue
        publisher = receipt(
            candidate, "Publish Dev Channel" if is_dev else "Release Publish"
        )
        if publisher is None or (is_dev and publisher["head_sha"] != producer):
            continue
        assert publisher["event"] == ("push" if is_dev else "workflow_run")
        if not is_dev:
            assert publisher["parent"]["name"] == "SemVer Release"
            assert publisher["parent"]["head_sha"] == producer
        if not all(
            v["result"] in {"success", "skipped"} for v in publisher["needs"].values()
        ):
            raise AssertionError("The QA publisher has an unexpected failed job")
        publisher_id = int(publisher["run_id"])
        sync = receipt(candidate, "Sync Integration Mirror", publisher_id)
        if sync is None or sync["needs"]["sync"]["result"] != "success":
            continue
        assert sync["event"] == "workflow_run"
        mirror_tag = tag.replace(".dev", "-dev.")
        mirrored = release(MIRROR, mirror_tag)
        if mirrored is None or asset(mirrored) is None:
            continue
        mirror_receipt = receipt(mirrored, "Release on tag")
        if mirror_receipt is None:
            continue
        assert mirror_receipt["event"] == "push"
        assert mirror_receipt["needs"]["release"]["result"] == "success"
        source_bytes = download(upstream["browser_download_url"])
        mirror_asset = asset(mirrored)
        assert source_bytes == download(mirror_asset["browser_download_url"])
        digest = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
        assert upstream["digest"] == mirror_asset["digest"] == digest
        pin = tag.removeprefix("v")
        dist = "ha-mcp-dev" if is_dev else "ha-mcp"
        with zipfile.ZipFile(io.BytesIO(source_bytes)) as archive:
            assert "manifest.json" in archive.namelist()
            assert "__init__.py" in archive.namelist()
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["domain"] == "ha_mcp_tools"
            assert manifest["version"] == pin.split(".dev")[0]
            assert f"{dist}=={pin}" in manifest["requirements"]
            assert json.loads(archive.read("hacs.json"))["zip_release"]
        for repo, ref in ((SOURCE, tag), (MIRROR, mirror_tag)):
            settings = contents(repo, "hacs.json", ref)
            assert (
                settings["zip_release"] and settings["filename"] == "ha_mcp_tools.zip"
            )
        jobs = api(SOURCE, f"actions/runs/{publisher_id}/jobs?per_page=100")
        publishing_job = next(
            j
            for j in jobs["jobs"]
            if j["name"]
            == ("Create GitHub pre-release" if is_dev else "Publish PyPI package")
        )
        steps = {s["name"]: s for s in publishing_job["steps"]}
        assert steps["Wait for the build on PyPI"]["conclusion"] == "success"
        assert (
            steps["Create pre-release" if is_dev else "Publish GitHub release"][
                "conclusion"
            ]
            == "success"
        )
        assert (
            steps["Wait for the build on PyPI"]["completed_at"]
            <= steps["Create pre-release" if is_dev else "Publish GitHub release"][
                "started_at"
            ]
        )
        metadata = json.loads(download(f"{INDEX}/pypi/{dist}/{pin}/json"))
        assert metadata["info"]["version"] == pin
        wheel = next(f for f in metadata["urls"] if f["packagetype"] == "bdist_wheel")
        assert (
            hashlib.sha256(download(wheel["url"])).hexdigest()
            == wheel["digests"]["sha256"]
        )
        target = api(SOURCE, "git/ref/tags/" + urllib.parse.quote(tag, safe=""))[
            "object"
        ]
        while target["type"] == "tag":
            target = api(SOURCE, "git/tags/" + target["sha"])["object"]
        assert target["type"] == "commit"
        site = None
        if not is_dev:
            site = json.loads(download(SITE + "/qa-release.json"))
            if site.get("version") != pin or site.get("parent_run_id") != publisher_id:
                continue
        return {
            "passed": True,
            "phase": phase,
            "product_sha": product,
            "source_tag": tag,
            "mirror_tag": mirror_tag,
            "digest": digest,
            "source_asset_id": upstream["id"],
            "mirror_asset_id": mirror_asset["id"],
            "source_publisher": publisher,
            "source_sync": sync,
            "mirror_publisher": mirror_receipt,
            "manifest": manifest,
            "site": site,
            "source_commit": target["sha"],
            "version": pin,
            "dist": dist,
            "wheel_url": wheel["url"],
            "wheel_digest": wheel["digests"]["sha256"],
        }
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("dev", "stable"))
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--producer-sha", required=True)
    parser.add_argument("--pr", type=int, default=14)
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_REPOSITORY") != FORK
        or os.environ.get("GITHUB_ACTIONS") != "true"
    ):
        raise ValueError("Only the personal-fork qualification workflow may report")
    if not all(
        re.fullmatch(r"[0-9a-f]{40}", s) for s in (args.product_sha, args.producer_sha)
    ):
        raise ValueError("Immutable product and producer commits are required")
    url = f"https://github.com/{FORK}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    result = {"passed": False, "phase": args.phase, "product_sha": args.product_sha}
    try:
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                value = verify_once(args.phase, args.product_sha, args.producer_sha)
            except urllib.error.HTTPError as error:
                if error.code not in {404, 502, 503, 504}:
                    raise
                value = None
            if value is not None:
                result = value
                break
            time.sleep(15)  # Bounded E2E assertion on real release availability.
        assert result["passed"], "The actual release handoff did not become ready"
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open(
                "a", encoding="utf-8"
            ) as output:
                output.writelines(
                    f"{key}={result[key]}\n"
                    for key in ("source_tag", "source_commit", "version", "mirror_tag")
                )
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        Path("qa-simple-zip-result.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        state = "success" if result["passed"] else "failure"
        api(
            FORK,
            "statuses/" + args.product_sha,
            {
                "state": state,
                "context": "Simple ZIP / " + args.phase,
                "description": "Real release handoff: " + state,
                "target_url": url,
            },
        )
        api(
            FORK,
            f"issues/{args.pr}/comments",
            {
                "body": f"[Agent] Simple ZIP real {args.phase} workflow chain: **{state}**. Tested `{args.product_sha}`. [Run and receipts]({url}). QA Python index/images; no production PyPI or MCP publication.",
            },
        )


if __name__ == "__main__":
    main()
