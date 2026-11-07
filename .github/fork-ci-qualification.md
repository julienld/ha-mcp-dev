# Personal fork CI qualification

This preparation-only PR verifies the permanent personal fork's existing
GitHub Actions and CodeRabbit integration. It changes no runtime code or tests.
This file is intentionally under `.github/` so the upstream path classifier
runs the complete validation lanes instead of skipping them as pure docs.

The PR targets the fork's clean `master` mirror. Do not merge it into that
mirror or promote it upstream. Close it after recording the actual checks
and review results in the personal administration runbook.

All real contributions start in this fork. An upstream PR, including a draft,
requires Julien's explicit approval for the specific contribution and revision.
Passing CI and receiving a bot review do not grant that approval.
