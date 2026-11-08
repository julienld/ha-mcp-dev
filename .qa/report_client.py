# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Report client discovery honestly, separately from installation qualification."""

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
    url = f"https://github.com/{verify.FORK}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    label = os.environ["QA_CLIENT_CORE"] + " / " + os.environ["QA_CLIENT_REPO"]
    verify.api(
        verify.FORK,
        "statuses/" + result["product_sha"],
        {
            "state": state,
            "context": "Simple ZIP / client discovery " + label,
            "description": "Installer UI exploration: " + state,
            "target_url": url,
        },
    )
    verify.api(
        verify.FORK,
        "issues/14/comments",
        {
            "body": f"[Agent] Installer UI discovery ({label}): **{state}**. [Run and observations]({url}). Product `{result['product_sha']}`. Discovery only; installer version-selection qualification is not asserted by this stage.",
        },
    )


if __name__ == "__main__":
    main()
