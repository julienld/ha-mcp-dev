# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Report only the installer assertions actually completed by the QA driver."""

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
    state = "success" if os.environ.get("QA_CLIENT_OUTCOME") == "success" else "failure"
    observation = (
        Path(os.environ["RUNNER_TEMP"]) / "simple-zip-client/client-observed.json"
    )
    qualified = (
        observation.exists()
        and json.loads(observation.read_text()).get("qualification_complete") is True
    )
    if not qualified:
        state = "failure"
    url = f"https://github.com/{verify.FORK}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    label = os.environ["QA_CLIENT_CORE"] + " / " + os.environ["QA_CLIENT_REPO"]
    verify.api(
        verify.FORK,
        "statuses/" + result["product_sha"],
        {
            "state": state,
            "context": "Simple ZIP / client discovery " + label,
            "description": "Actual installer version selection: " + state,
            "target_url": url,
        },
    )
    verify.api(
        verify.FORK,
        "issues/14/comments",
        {
            "body": f"[Agent] Installer version selection ({label}): **{state}**. [Run and observations]({url}). Product `{result['product_sha']}`. "
            + (
                "Old archive selected and installed through the actual UI, then explicit ZIP → old archive → ZIP installs; installed files compared with the published ZIP."
                if qualified
                else "Qualification incomplete; inspect the UI observations before drawing a product conclusion."
            ),
        },
    )


if __name__ == "__main__":
    main()
