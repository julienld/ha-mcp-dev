# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Report the actual HA test outcome on the exact personal-fork PR revision."""

import json
import os
from pathlib import Path

import verify


def main() -> None:
    if (
        os.environ.get("GITHUB_REPOSITORY") != verify.FORK
        or os.environ.get("GITHUB_ACTIONS") != "true"
    ):
        raise ValueError("Unexpected qualification reporter")
    result = json.loads(Path("qa-simple-zip-result.json").read_text(encoding="utf-8"))
    receipt_path = (
        Path(os.environ["RUNNER_TEMP"]) / "simple-zip-ha/ha-install-receipt.json"
    )
    receipt = (
        json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt_path.exists()
        else {}
    )
    passed = os.environ.get("QA_HA_OUTCOME") == "success" and bool(
        receipt.get("baselines")
    )
    state = "success" if passed else "failure"
    url = f"https://github.com/{verify.FORK}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    verify.api(
        verify.FORK,
        "statuses/" + result["product_sha"],
        {
            "state": state,
            "context": "Simple ZIP / HA " + result["phase"],
            "description": "Published ZIP installation in HA: " + state,
            "target_url": url,
        },
    )
    verify.api(
        verify.FORK,
        "issues/14/comments",
        {
            "body": f"[Agent] Simple ZIP actual HA {result['phase']} installation: **{state}**. Tested `{result['product_sha']}`, source `{result['source_tag']}`. [Run and receipts]({url}). Existing update/reinstall/restart/MCP case with the actually published ZIP and wheel.",
        },
    )


if __name__ == "__main__":
    main()
