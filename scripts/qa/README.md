# Isolated ZIP release qualification

This branch is a temporary qualification harness for the two fork PRs. It is
not proposed for upstream or for the fork's clean `master` mirror.

Dispatch the existing `e2e-tests.yml` workflow on this branch with
`update_path_only=true` and `proof_variant=assets` or `activation`. Each dispatch
checks out the immutable subject registered in `zip_release_proof.py`, separate
from the harness checkout. Its sandbox uses the fork's job-scoped token only.

The sandbox executes the subject's mirror staging, verification, asset copy and
release creation shell steps against real GitHub objects. It checks draft
recovery, digest rejection, preservation of the counted asset across retries,
and recovery after the source release is removed. The activation variant also
executes its finalizer against real annotated tags and compare-and-swap pushes,
including a concurrent alias update, retry, and refusal to move backwards.

Every remote write is confined to `julienld/ha-mcp-dev` and temporary
`qa-zip-<run>-<attempt>-<variant>-...` refs/releases. Protected refs and latest
release identity are recorded before and after the proof. Cleanup always runs;
its failure fails the job. In a fork without stable releases, GitHub's latest
endpoint can temporarily select an owned QA release despite `make_latest=false`.
Only an ID created by that run is allowed during the proof; cleanup must restore
the exact original latest-release identity. Git refs never get this exception.
The report, cleanup state and exact downloaded ZIP
are retained as artifacts for 14 days. If the runner dies before cleanup,
use its `state.json` to remove only that run's exact QA release IDs and tag
names; never delete by a broad wildcard.

The existing HA update-path lane consumes the downloaded ZIP via a pytest
plugin. The normal builder still runs and its members must match; the archive
installed by the working-tree scenario is then replaced with the actual
downloaded bytes. A receipt is mandatory and all existing HA assertions remain.
The release and HA results are attached to the exact tested fork-PR commit.

This qualification deliberately adapts tag/ref labels to the QA namespace and
forces `make_latest=false` for stable-looking finalizer releases. The normal
production aliases are never moved. The snapshot's workflow deployment key and
cross-repository permissions are not exercised: snapshot commits omit workflow
files, and release shell steps run directly in the runner. Automatic event
handoff, historical release backfill and HACS/Marketplace catalog selection
still need their own production rollout verification.
