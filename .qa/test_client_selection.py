"""Observe and exercise real installer UIs against the isolated QA releases."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import requests
import verify
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright
from testcontainers.core.container import DockerContainer
from websockets.sync.client import connect


def ws(url: str, token: str, message: dict) -> object:
    uri = url.replace("http://", "ws://") + "/api/websocket"
    with connect(uri, open_timeout=15) as websocket:
        assert json.loads(websocket.recv(timeout=15))["type"] == "auth_required"
        websocket.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(websocket.recv(timeout=15))["type"] == "auth_ok"
        websocket.send(json.dumps({"id": 1, **message}))
        while True:
            reply = json.loads(websocket.recv(timeout=180))
            if reply.get("id") == 1 and reply.get("type") == "result":
                if not reply.get("success"):
                    raise RuntimeError(json.dumps(reply.get("error")))
                return reply.get("result")


def test_client_selection() -> None:
    os.environ["E2E_NO_TOOLS_ENTRY"] = "1"
    sys.path.insert(0, os.environ["QA_CLIENT_SOURCE"])
    from tests.src.e2e._conftest_testcontainer import _prepare_testcontainer_config
    from tests.src.e2e.workflows.embedded.test_embedded_update_path import _wait_http_ok
    from tests.test_constants import TEST_PASSWORD, TEST_TOKEN, TEST_USER

    args = SimpleNamespace(
        core=os.environ["QA_CLIENT_CORE"],
        repo=os.environ["QA_CLIENT_REPO"],
        output=Path(os.environ["QA_CLIENT_OUTPUT"]),
    )
    assert args.core in {"2026.8.0", "2026.11.0"}
    assert args.repo in {"source", "mirror"}
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != verify.FORK
    ):
        raise ValueError("Only the isolated fork runner may launch these clients")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["E2E_NO_TOOLS_ENTRY"] = "1"
    config, temp_dir, _, _ = _prepare_testcontainer_config(False)
    config = Path(config)
    assert config.is_relative_to(Path(tempfile.gettempdir()))
    storage = config / ".storage/core.config_entries"
    entries = json.loads(storage.read_text())
    entries["data"]["entries"] = [
        e for e in entries["data"]["entries"] if e["domain"] in {"hacs", "sun"}
    ]
    storage.write_text(json.dumps(entries), encoding="utf-8")
    for name in (
        "home-assistant_v2.db",
        "home-assistant_v2.db-wal",
        "home-assistant_v2.db-shm",
    ):
        (config / name).unlink(missing_ok=True)
    assert not (config / "custom_components/ha_mcp_tools").exists()
    repository = verify.SOURCE if args.repo == "source" else verify.MIRROR
    domain = "hacs" if args.core == "2026.8.0" else "marketplace"
    result = {
        "core": args.core,
        "backend": domain,
        "repository": repository,
        "qualification_complete": False,
    }
    container = DockerContainer(f"ghcr.io/home-assistant/home-assistant:{args.core}")
    page = None
    playwright = None
    browser = None
    container.with_exposed_ports(8123).with_volume_mapping(str(config), "/config", "rw")
    for name, value in {
        "PIP_INDEX_URL": verify.INDEX + "/simple/",
        "PIP_EXTRA_INDEX_URL": "https://pypi.org/simple",
        "UV_INDEX_URL": verify.INDEX + "/simple/",
        "UV_EXTRA_INDEX_URL": "https://pypi.org/simple",
        "UV_INDEX_STRATEGY": "unsafe-best-match",
        "TZ": "UTC",
    }.items():
        container.with_env(name, value)
    try:
        container.start()
        base = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8123)}"
        _wait_http_ok(base + "/api/", {"Authorization": "Bearer " + TEST_TOKEN}, 180)
        result["api_version"] = requests.get(
            base + "/api/config",
            headers={"Authorization": "Bearer " + TEST_TOKEN},
            timeout=20,
        ).json()["version"]
        deadline = time.monotonic() + 180
        while True:
            api_config = requests.get(
                base + "/api/config",
                headers={"Authorization": "Bearer " + TEST_TOKEN},
                timeout=20,
            ).json()
            if domain in api_config["components"]:
                break
            if time.monotonic() >= deadline:
                result["loaded_components"] = api_config["components"]
                raise AssertionError(f"{domain} never completed HA setup")
            time.sleep(2)
        playwright = sync_playwright().start()
        if playwright is not None:
            executable = shutil.which("google-chrome") or shutil.which(
                "google-chrome-stable"
            )
            if executable is None:
                raise RuntimeError("The hosted test runner has no Chrome executable")
            browser = playwright.chromium.launch(
                executable_path=executable,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(
                viewport={"width": 1400, "height": 1000}, locale="en-US"
            )
            page.goto(base + "/", wait_until="domcontentloaded")
            page.locator('input[name="username"]').fill(TEST_USER, timeout=90000)
            page.locator('input[name="password"]').fill(TEST_PASSWORD)
            page.get_by_role("button", name="Log in", exact=True).click()
            page.locator("ha-sidebar").wait_for(timeout=90000)
            if domain == "marketplace":
                ws(base, TEST_TOKEN, {"type": "marketplace/warning/accept"})
            repository_id = str(verify.api(repository, "")["id"])
            ws(
                base,
                TEST_TOKEN,
                {
                    "type": domain + "/repositories/add",
                    "repository": repository,
                    "category": "integration",
                },
            )
            ws(
                base,
                TEST_TOKEN,
                {
                    "type": domain + "/repository/beta",
                    "repository": repository_id,
                    "show_beta": True,
                },
            )
            info = ws(
                base,
                TEST_TOKEN,
                {"type": domain + "/repository/info", "repository_id": repository_id},
            )
            result["repository_before"] = {
                key: info.get(key)
                for key in (
                    "full_name",
                    "available_version",
                    "installed",
                    "ref",
                    "file_name",
                    "beta",
                    "releases",
                )
            }
            assert info["full_name"] == repository and not info["installed"]
            page.goto(
                base + "/" + domain + "/repository/" + repository_id,
                wait_until="domcontentloaded",
            )
            if domain == "hacs":
                page.locator("iframe").first.wait_for(timeout=60000)
            page.screenshot(
                path=str(args.output / "repository-loading.png"), full_page=True
            )
            scope = (
                page.frame_locator("iframe").first
                if page.locator("iframe").count()
                else page
            )
            scope.get_by_text(
                "Manage Home Assistant with AI", exact=False
            ).first.wait_for(timeout=60000)
            result["repository_ui"] = scope.locator("body").aria_snapshot()
            page.screenshot(path=str(args.output / "repository.png"), full_page=True)
            download = scope.get_by_role(
                "button", name=re.compile("Télécharger|Download", re.IGNORECASE)
            )
            if download.count():
                download.first.click()
                dialog = scope.locator("hacs-download-dialog")
                visible_dialog = scope.get_by_role("alertdialog")
                visible_dialog.wait_for(timeout=30000)
                result["download_dialog"] = visible_dialog.aria_snapshot()
                page.screenshot(
                    path=str(args.output / "download-dialog.png"), full_page=True
                )
                dialog.get_by_role(
                    "button",
                    name=re.compile(
                        "version différente|different version", re.IGNORECASE
                    ),
                ).click()
                dialog.get_by_role("combobox").click(timeout=30000)
                result["version_options"] = scope.locator("body").aria_snapshot()[
                    -8000:
                ]
                scope.get_by_role("option", name=re.compile(r"v9\.1\.1\b")).click()
                dialog.get_by_role(
                    "button", name=re.compile("^Télécharger$|^Download$", re.IGNORECASE)
                ).click()
                expect(visible_dialog).not_to_be_visible(timeout=180000)
            else:
                raise AssertionError("No actual installer download action")
            component = config / "custom_components/ha_mcp_tools"

            def installed() -> dict:
                info = ws(
                    base,
                    TEST_TOKEN,
                    {
                        "type": domain + "/repository/info",
                        "repository_id": repository_id,
                    },
                )
                manifest = json.loads((component / "manifest.json").read_text())
                assert info["installed"]
                return {
                    "ref": info.get("ref"),
                    "installed_version": info.get("installed_version"),
                    "manifest_version": manifest["version"],
                }

            result["old_first_install"] = installed()
            assert result["old_first_install"]["manifest_version"] == "9.1.1"
            latest = info["available_version"]
            published = verify.release(repository, latest)
            asset = verify.asset(published)
            assert asset is not None
            published_zip = verify.download(asset["browser_download_url"])
            result["zip_sha256"] = hashlib.sha256(published_zip).hexdigest()
            result["zip_asset_id"] = asset["id"]
            with zipfile.ZipFile(io.BytesIO(published_zip)) as archive:
                expected = {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if not name.endswith("/")
                }
            result["explicit_version_installs"] = []
            for target in (latest, "v9.1.1", latest):
                ws(
                    base,
                    TEST_TOKEN,
                    {
                        "type": domain
                        + (
                            "/repository/download"
                            if domain == "hacs"
                            else "/repository/install"
                        ),
                        "repository": repository_id,
                        "version": target,
                    },
                )
                observed = installed()
                observed["requested_version"] = target
                if target == "v9.1.1":
                    assert observed["manifest_version"] == "9.1.1"
                else:
                    assert all(
                        (component / name).read_bytes() == value
                        for name, value in expected.items()
                    )
                result["explicit_version_installs"].append(observed)
            result["qualification_complete"] = True
            result["observed"] = True
    except Exception as error:
        result["error"] = str(error)
        if page is not None:
            try:
                result["last_ui"] = page.locator("body").aria_snapshot()
                result["frames"] = [
                    {"url": frame.url, "ui": frame.locator("body").aria_snapshot()}
                    for frame in page.frames
                ]
                result["buttons"] = page.get_by_role("button").all_text_contents()
                page.screenshot(
                    path=str(args.output / "client-error.png"), full_page=True
                )
            except (PlaywrightError, OSError) as capture_error:
                result["capture_error"] = str(capture_error)
        raise
    finally:
        (args.output / "client-observed.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
        container.stop()
        shutil.rmtree(temp_dir, ignore_errors=True)
