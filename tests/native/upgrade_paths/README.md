# Main to Native upgrade qualification

Dispatch the already registered `native-migration.yml` on the complete candidate
branch with `target=upgrade_paths`. It calls `native-upgrade-paths.yml`; no release,
tag, upstream contribution, household instance or public tunnel is created.

The workflow resolves `homeassistant-ai/ha-mcp`'s actual default branch (`master`
today), freezes its full SHA, and builds its own wheel and component. It builds
the Native candidate independently from the dispatched SHA. Application source
is never replaced with harness code. The only component manifest substitution is
the existing qualification helper's local paired-wheel URL; candidate wheel hashes
and dependency policy remain enforced.

One isolated runner exercises these five profiles sequentially:

| Existing connection | Authentication retained |
|---|---|
| Separate server port and secret path | Secret URL, no added Bearer header |
| HA webhook and secret ID | Secret URL, no added Bearer header |
| HA webhook | Existing HA long-lived Bearer token |
| HA webhook, HA account OAuth | Existing DCR client, PKCE grant and refresh token |
| HA webhook, legacy OAuth | Existing static client ID/secret, PKCE grant and refresh token |

Each profile starts Main on a fresh, disposable HA configuration with two real
run-local administrators. HA account OAuth uses Core's actual password login
flow; the test does not mint an authorization code or replace a token endpoint.
Only this initial phase enrolls the client. Later phases have no login or DCR
fallback. An immutable client descriptor hash guards its URL, authentication
method and OAuth identity; legitimate refresh-token rotation stays in the
separate in-memory token cache.

The same HA config directory, entry IDs, webhook/secret IDs, signing keys, Core
image digest and host ports survive the following sequence:

1. Connect to Main and create a persisted input-boolean state through MCP.
2. Stop Core gracefully, replace the paired component/library with the Native
   distribution, and restart. The old entry must remain Legacy automatically.
3. Select Native and its human owner through HA's real options flow, then restart.
4. Restart the candidate again with the same configuration and client.

Every phase checks MCP revisions `2025-06-18`, `2025-11-25` and `2026-07-28`, tool
names/input schemas/safety annotations, reads, service effects and the persisted
state. OAuth refresh must use the cached original endpoint and existing grant;
the returned token must reconnect to MCP. Writes are never replayed after an
uncertain response. Runtime hashes attest the installed package and component
against the built artifacts. A new session after a Core restart is normal; this
does not claim uninterrupted sessions or SSE resume across server downtime.

The workflow exposes two separate gates:

- **Upgrade retains existing Legacy clients** requires all five Main and upgraded
  profiles to pass.
- **Explicit Native switch retains the same clients** additionally requires Native
  and the final restart. The old separate port is currently unsupported in Native,
  so this gate must fail for that profile. There is no URL rewrite, alternate
  endpoint, expected-failure waiver or skipped profile to turn it green.

New tools and optional parameters are allowed. Changed existing input contracts
and annotations are reported as deltas, without migration-specific exemptions.
Schema comparison is conservative structural evidence, not a proof of semantic
equivalence. A single service witness cannot qualify every tool's semantics.

Only sanitized `report.json` is uploaded. Configs, generated credentials, OAuth
grants and raw logs remain private and are destroyed by label-scoped cleanup.
Missing profiles, failed setup, substituted source, changed client settings,
failed refresh, missing state or unconfirmed cleanup fail qualification.

This initial matrix covers the embedded HTTP component on one supported Core
image and amd64. It does **not** qualify stdio, external servers, Home Assistant
app (add-on) upgrades on HAOS,
ARM, Core-version upgrades, MFA/browser UI, client-vendor behavior, Cloudflare or
Nabu Casa routing. Those require additional migration scenarios before claiming
compatibility across every deployment. Existing clean-install CI does not replace
those upgrade scenarios.

For host-import validation without Docker:

```powershell
uv run --locked -s tests/native/upgrade_paths/run.py preflight --state local/unused-upgrade-state.json
```
