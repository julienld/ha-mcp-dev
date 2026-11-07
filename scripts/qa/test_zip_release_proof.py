# /// script
# requires-python = ">=3.13"
# dependencies = ["PyYAML==6.0.3", "packaging==26.3"]
# ///
"""Exercise the QA publisher's repository, namespace and mutation guards offline."""

import unittest

from zip_release_proof import REPOSITORY, Proof, checked_context


class PublicationGuards(unittest.TestCase):
    def test_publication_requires_the_registered_fork_manual_runner(self) -> None:
        environment = {
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "RUNNER_OS": "Linux",
            "GITHUB_REF": "refs/heads/qualify/zip-release-proof-20261107",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GH_TOKEN": "fake",
        }
        self.assertEqual(checked_context(environment, "assets"), "qa-zip-123-1-assets")
        for key, value in {
            "GITHUB_REPOSITORY": "homeassistant-ai/ha-mcp",
            "GITHUB_EVENT_NAME": "push",
            "RUNNER_OS": "Windows",
            "GITHUB_REF": "refs/heads/master",
            "GITHUB_RUN_ID": "../123",
            "GITHUB_RUN_ATTEMPT": "0",
            "GH_TOKEN": "",
        }.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                checked_context({**environment, key: value}, "assets")
        with self.assertRaises(ValueError):
            checked_context(environment, "unknown")

    def test_writes_cannot_escape_owned_tags_releases_and_commit_trees(self) -> None:
        proof = Proof.__new__(Proof)
        proof.prefix = "qa-zip-123-1-assets"
        tag = proof.tag("source")
        proof.owned_objects = {"subject"}
        proof.state = {
            "tags": {tag: "subject"},
            "release_ids": [42],
            "subject_tree": "tree",
        }
        proof.check_write(
            "git/refs", "POST", {"ref": "refs/tags/" + tag, "sha": "subject"}
        )
        proof.check_write(
            "releases/42", "PATCH", {"draft": False, "make_latest": "false"}
        )
        for path, method, fields in [
            ("git/refs", "POST", {"ref": "refs/heads/master", "sha": "subject"}),
            ("git/refs/tags/stable", "PATCH", {"sha": "subject"}),
            ("git/refs/tags/" + tag, "PATCH", {"sha": "foreign"}),
            ("git/refs/tags/qa-zip-999-1-assets-source", "DELETE", {}),
            ("git/commits", "POST", {"tree": "other", "parents": ["subject"]}),
            ("releases/43", "DELETE", {}),
            ("releases/42", "PATCH", {"draft": False}),
        ]:
            with self.subTest(path=path, fields=fields), self.assertRaises(ValueError):
                proof.check_write(path, method, fields)


if __name__ == "__main__":
    unittest.main()
