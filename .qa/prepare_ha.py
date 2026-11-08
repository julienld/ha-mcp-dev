# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Download the exact workflow-produced integration and wheel for HA testing."""

import argparse
import hashlib
import json
from pathlib import Path

import verify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads(args.input.read_text(encoding="utf-8"))
    if not result["passed"]:
        raise ValueError("An unsuccessful workflow chain cannot seed HA evidence")
    release = verify.release(verify.MIRROR, result["mirror_tag"])
    archive = verify.download(verify.asset(release)["browser_download_url"])
    assert "sha256:" + hashlib.sha256(archive).hexdigest() == result["digest"]
    wheel = verify.download(result["wheel_url"])
    assert hashlib.sha256(wheel).hexdigest() == result["wheel_digest"]
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ha_mcp_tools.zip").write_bytes(archive)
    (args.output / "ha-input.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"source_tag": result["source_tag"], "digest": result["digest"]}))


if __name__ == "__main__":
    main()
