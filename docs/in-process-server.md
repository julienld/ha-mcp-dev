# Run the MCP server inside Home Assistant

The **HA-MCP — Manage Home Assistant with AI** (`ha_mcp_tools`) provides native MCP and an
LLM API for Assist. Both use the same tool definitions and policy checks.
The native runtime runs on Home Assistant's event loop and HTTP listener,
without a separate server port or an internal Home Assistant access token.

The **HA-MCP integration** (`ha_mcp_tools`) can run the **full ha-mcp server
in-process**, inside the Home Assistant application, and expose it remotely
through a Home Assistant webhook. This is one of the ways to run ha-mcp — and the
recommended one. It is a complete, standalone ha-mcp install — a replacement for
the app (add-on), Docker, and uvx/PyPI (stdio) server, not an addition to them. Run
only one ha-mcp server; never run the in-process server alongside another
install.

Existing entries keep their selected runtime, authentication and connection
identifiers. Updating the component does not automatically switch a Legacy
entry to Native or migrate an external app, Docker or Python installation.

## Who it's for

The component works with Home Assistant OS, Supervised, Container and Core.
It can serve MCP clients, conversation agents using HA's LLM API, or both.
An external ha-mcp server remains a supported alternative. Configure each
client to use the intended server rather than adding duplicate connections.

## How it works

Home Assistant installs the library paired with the selected component
release, under its normal dependency constraints. Native tools call Core's
services, registries and other owners directly. MCP requests arrive through
Home Assistant's HTTP server; Assist calls enter the shared Engine directly.

Blocking file work uses Home Assistant's executor. Removing the separate
server thread does not remove ordinary background tasks or make blocking work
safe to execute on the event loop.

Legacy mode retains the older embedded server and its REST/WebSocket client.
Its port, credentials and advanced package override are compatibility settings,
not requirements of Native mode.

## Requirements

Each release declares its required Home Assistant version in HACS/Marketplace.
The supported window is the current stable monthly Core release and the
previous one. A new monthly release advances the CI window; a new ha-mcp
release must declare the corresponding minimum before publication.
An already-installed ha-mcp version does not stop working merely because
another month begins.

The initial native adoption floor is Core 2026.10.0. Use a component release
compatible with your installed Core; update Core before installing a release
that requires a newer version.

## Setup

1. Install **HA-MCP — Manage Home Assistant with AI** using HACS, or Marketplace on Core versions
   that provide it. Add `homeassistant-ai/ha-mcp` as an integration repository
   if it is not listed. An existing installation from the
   `homeassistant-ai/ha-mcp-integration` mirror can keep that repository.
2. Restart Home Assistant after replacing an already-loaded component.
3. Open **Settings → Devices & Services → Add Integration**, find
   **HA-MCP — Manage Home Assistant with AI**, and choose **HA-MCP Server**.
4. Select an active administrator as the owner. Native setup does not ask you
   to create an administrator account or mint an internal access token.
5. Enable the access you need: MCP through Home Assistant, LLM API export to
   Assist, or both. New entries leave these choices disabled until selected.
6. For MCP, copy the exact connection URL from the entry's **Configure** screen.
   For Assist, select the exported API in your conversation agent's settings.

For manual installation, extract the selected release's `ha_mcp_tools.zip`
into `config/custom_components/ha_mcp_tools/`. Preserve its manifest and paired
library requirement. Do not mix component files and library wheels from
different releases.

In the navigation paths below, older installed releases use **HA-MCP Custom
Component** where the new release uses **HA-MCP — Manage Home Assistant with AI**.
Searching for **HA-MCP** finds either name.

1. **Install the component.** Install **HA-MCP — Manage Home Assistant with AI** from HACS,
   or on Home Assistant 2026.11+ from the built-in **Marketplace** after accepting
   its first-run warning and searching for **HA-MCP**. It is
   in the default catalog, so Marketplace installs need no connected GitHub account
   or custom repository. In HACS, search for **HA-MCP** and **Download**.
   An install from the earlier
   `homeassistant-ai/ha-mcp-integration` mirror keeps receiving the same
   releases; on the Marketplace, keep GitHub connected for background checks on
   that custom repository. Or, without
   HACS, copy the `custom_components/ha_mcp_tools` directory from this repository
   into your Home Assistant `config/custom_components/` directory (so you end up
   with `config/custom_components/ha_mcp_tools/`). Restart Home Assistant.
2. **Add the in-process server entry.** Go to **Settings → Devices & Services →
   Add Integration**, search for **HA-MCP**, and — on the menu
   that appears — choose **HA-MCP Server**. The server acts with an
   administrator account's permissions, so the form asks for one of two
   things:
   - **An administrator access token.** Your own works: open your profile
     (your name at the bottom of the sidebar), select the **Security** tab, and
     under **Long-lived access tokens** select **Create token**. It also works
     from outside your home network if it ever leaks, and Home Assistant
     records the server's changes under your name.
   - **The login of an account made just for HA-MCP** (safer). Create it under
     **Settings → People → Add person** with **Allow login**, **Local access
     only** and **Administrator** on, the way you would make one for an MQTT
     client, then enter its user name and password. HA-MCP creates its token,
     named **HA-MCP Server**, so nobody has to log in as it, and the password is
     not kept. Its token works only from your local network, where the server
     runs, and Home Assistant records the server's changes under that account.
     Never enter your own login there: to use your own account, paste its
     token. The login does not ask for the account's multi-factor code; only an
     administrator can open this form.

   It also asks how MCP clients may reach
   the server: **Remote access through Home Assistant**
   (disabled by default; choose Home Assistant sign-in, legacy OAuth or the
   secret URL to let clients connect through a webhook) and **Network access**
   (this machine only by default; choose local network to let devices on your
   network use the direct port). Submitting creates the entry and starts the
   server. (If you already have
   the **HA-MCP File & YAML Tools** entry, use the same **Add Integration** flow;
   the two entries appear together under the one integration tile.)
3. **Copy your connect URL.** As soon as the server starts, a notification titled
   **HA-MCP Server** confirms it is running and points you to the URL. The
   connect URL itself is on the entry's **Configure** screen (**Settings →
   Devices & Services → “HA-MCP — Manage Home Assistant with AI” → HA-MCP Server → Configure**),
   which only administrators can open, because the URL is the credential. The
   notification and the Home Assistant log deliberately carry no URL:
   notifications are visible to every signed-in user, and the log reaches
   connected MCP clients through the server's own log tools.
4. **Connect your MCP client** to that URL.

To pause the server, **disable** its config entry (**Settings → Devices &
Services → “HA-MCP — Manage Home Assistant with AI” → HA-MCP Server → ⋮ → Disable**);
re-enable it to start it again. Removing the entry stops the server; the token
you entered stays valid until you delete it from your profile.

## Connect URLs

Native uses Home Assistant's existing address, locally or through your
configured remote access. Use the URL shown in Configure; treat secret URLs
as credentials and keep them out of logs and issue reports.

The main MCP URL follows this entry's tool-search setting. Append
`/catalog/full` to always list every permitted tool, or `/catalog/search`
to always expose pinned tools with search and dispatch tools. Append
`/readonly/catalog/full` or `/readonly/catalog/search` for the same choices
with writes refused. These URLs share the entry's authentication and tool
restrictions; selecting a catalog does not grant additional access.

A Legacy direct-port connection has no corresponding native listener.
Switching such an entry to Native requires updating the client's URL.
HA-hosted webhook identifiers and existing authentication identities are
preserved when the same entry changes runtime.

## Chat with the toolset from Home Assistant (conversation agents / voice)

Enable the conversation-agent LLM API export in the server entry, then select
the HA-MCP API in a conversation integration that supports Home Assistant LLM
APIs. It does not require the MCP webhook to be enabled.

### Exposure modes

- **Tool search** exposes pinned tools plus search and dispatch tools.
- **Full catalog** exposes every permitted tool directly.
- **Both** makes both API presentations available for conversation agents.

### Per-tool exposure

The HA-MCP settings panel controls which tools are exposed through the LLM API.
Global enablement, read-only mode, approvals and per-tool exposure remain
effective when a tool is called indirectly. Existing exposure choices and API
identifiers survive upgrades.

Native Assist calls require an identified, active administrator. A voice
satellite that supplies no usable user identity is refused; it does not inherit
the configured administrator's authority. Core's LLM interface does not carry
every rich MCP result or continuation. Image-only calls are refused before
execution; mixed results retain their usable data and report the image limitation.

The reverse bridge, importing selected Core LLM APIs into MCP, is a separate
explicit option. Enabling one direction does not implicitly enable the other.

## Settings panel ("HA-MCP" in the sidebar)

The sidebar panel uses Home Assistant authentication. Every request checks the
active administrator session. Native serves settings locally; Legacy proxies
its embedded server. The connection secret is not placed in panel URLs.

## Independent from the app

The component and the Home Assistant MCP Server app are independent
installations. An ordinary update preserves the installation method.
The component's File & YAML entry can also support an external server without
starting an embedded server.

## Options

Configure the server entry to choose its runtime, authentication, owner, MCP
access and LLM bridges. Preserve the existing entry when upgrading; deleting
and recreating it changes identifiers that clients may have saved.

### Server updates

`ha_manage_ha_mcp_updates(action="check")` identifies the running installation
and its update capability. `action="guide"` explains its installation manager
and upgrade steps. `action="update"` applies an ordinary update where a
qualified manager is available.

The tool preserves the current runtime, authentication and repository origin.
Detected breaking changes, or insufficient release information, produce a plan
before code is changed. An ordinary restart requirement is distinguished from
a change to the connection contract.

Installed files and running code are different states. A component update
reports `pending_restart` until a Core restart activates the new code.
After restarting, check the version again. A lost response is not an invitation
to repeat an installation: the update tool records dispatched attempts and
inspects the installed version before allowing further work.

Open **Settings → Devices & Services → “HA-MCP — Manage Home Assistant with AI” → HA-MCP Server → Configure** to change these. Saving the options reloads the server so
the changes take effect; a change to the OAuth callback list alone applies to the
next sign-in without a reload, and **Turn access off after a restart** applies at
the next Home Assistant start. (The **HA-MCP File & YAML Tools** entry has no options — a
Configure there just reports that.)

| Option | Default | What it does |
|--------|---------|--------------|
| **Server port** | `9584` | Local TCP port the server listens on. `9584` avoids the app's `9583` so an existing app install does not conflict. |
| **Network access** | this machine only (`127.0.0.1`) for new installs | `127.0.0.1` restricts direct access to the Home Assistant machine. Local network makes the port reachable on your LAN with the secret path as the credential, like the app: over IPv4, and over IPv6 from the local network only (extra IPv6 networks can be allowed under **Extra IPv6 networks allowed** in the settings panel). The webhook and panel work either way. Entries created before setup asked for it keep local network unless you change it. |
| **Authentication mode** | as chosen at setup (`ha_auth` when remote access was left disabled) | `none`: the secret webhook URL is the credential. `ha_auth`: clients sign in with your Home Assistant account. `legacy`: self-hosted OAuth with a static Client ID + Secret, for clients that need a credential to paste. See [Security](#security). |
| **ha-mcp package (advanced)** | empty (the server this component release installed) | Leave it empty unless you are testing a specific build — it accepts any pip requirement string, including a version pin, a pull-request tarball or a wheel URL. Saving it reinstalls the server and restarts it in place, without restarting Home Assistant; clearing it returns to the paired server. See [Server updates](#server-updates). |
| **Home Assistant URL for the server (advanced)** | empty (derived from your HA's http config) | How the in-process server reaches Home Assistant. Empty derives the URL from your instance's real port, SSL setting and listen address: loopback by default, or the first listen address when you restricted them under HTTP server settings. An SSL-enabled HA is reached with certificate verification off, since its certificate is issued for its hostname rather than this address. The `ha_auth` sign-in always uses the derived route for its token exchange. Only set a value when the server must take a different route entirely. |
| **Remote access via webhook** | off for new installs (as chosen at setup) | Turn off for local-only mode: the webhook is never registered, so Home Assistant (including Nabu Casa) cannot reach the server at all. Direct port access and the sidebar panel keep working. |
| **Turn access off after a restart** | off | Start with the **Access** switch off after every Home Assistant restart, instead of keeping its last state. Enable the switch first: while it is disabled, nothing can turn access back on. See [Turning access on and off](#turning-access-on-and-off). |
| **Conversation-agent LLM API** | on | Offers the toolset to Home Assistant conversation agents — see [Chat with the toolset](#chat-with-the-toolset-from-home-assistant-conversation-agents--voice). Enabling only makes it selectable per agent; turn off to remove it from every agent's selector. |
| **Conversation-agent tool exposure** | `tool_search` | Shape of the toolset agents get: compact tool-search API (default), the full catalog, or both side by side (choose per agent). See [Exposure modes](#exposure-modes). |
| **External URL (optional)** | empty | Shown as the primary connect URL - for your own domain / reverse proxy (e.g. `https://ha.example.com`). Opening it should reach your HA login page, and must not contain a port like `:8123` (any port breaks remote MCP clients). Empty = Nabu Casa / local automatically. |
| **Custom webhook secret (optional)** | empty | Replaces the random webhook secret in `/api/webhook/<secret>`. The URL is the credential - use a long, hard-to-guess value. |
| **Custom direct-access path (optional)** | empty | Replaces the random `/private_...` path on the server port. Same rule: the path is the credential. |
| **Regenerate connect secrets now** | off | One-time action: mints fresh random values for both secrets, immediately invalidating the old connect URLs (and clearing the two overrides). |
| **Allowed OAuth callback URLs** | the common clients' callbacks (below) | In `none` mode, the only callback URLs an OAuth sign-in is sent back to. Also editable in the **HA-MCP** sidebar panel under **Server Settings → Remote access**. See [Security](#security). |
| **Allow any OAuth callback URL** | off | In `none` mode, accept any well-formed callback instead of only the **Allowed OAuth callback URLs**. See [Security](#security). |

### Server updates

The server is part of the component release. Each HA-MCP integration
release names the exact `ha-mcp` build it was released with as an integration
requirement, and Home Assistant installs it like any integration's Python
packages. For HACS- or Marketplace-managed installs, update the component from
its update entity under **Settings → System → Updates**; manual
installs can replace the component files with the new release. Either path
carries the matching server, and restarting Home Assistant after the update
installs both. The component never downloads or swaps the server on its own.

HA-MCP is in the default catalog, which the Marketplace refreshes every six
hours without a GitHub connection. Custom repositories, including the legacy
distribution mirror, still need a GitHub connection for the Marketplace's
48-hour background checks. To have a newly updated server ask for a repository
refresh right away, turn on **Refresh the component in HACS after an update** in
the settings panel's Advanced settings (Operations); installs that already did
this before it became optional keep it on.

**Development builds** follow the main branch. Turn on the **Pre-release**
switch of the HA-MCP repository (in HACS, or on its Marketplace
device, where the entity starts disabled, on Home Assistant 2026.11+) to receive them; each
pre-release pins the exact `ha-mcp-dev` build published from the same commit.
Turn the switch off to return to stable releases with the next stable update.
Moving between the two swaps `ha-mcp-dev` and `ha-mcp` as described below.

App, Docker and Python installations receive the path appropriate to their
actual owner. When the running process cannot safely control that owner, the
tool provides instructions instead of pretending to update itself.

### Upgrading from component 2.x

Keep the current entry. Migration preserves identifiers, explicit LLM choices
and historical effective export behavior. The earlier package-override cleanup
is applied only to entries that have not already passed it.

Existing Legacy credentials remain available for rollback. Native does not
use them for Core operations. A native-only entry needs an explicitly
configured valid credential before it can run Legacy mode.

To roll back code, install a compatible previous component release and its
paired library, then restart Core. Code rollback does not reverse changes made
to entities or configuration; restore the appropriate data backup separately.

### Local-only mode

An Assist-only installation can leave MCP access disabled. For MCP clients on
the LAN, use Home Assistant's local address. Whether Home Assistant itself is
reachable remotely is controlled by your HA remote-access configuration.

### Turning access on and off

The optional **Access** switch closes MCP and the LLM API while preserving the
entry. It is disabled as an entity by default and is not exposed to Assist by
default. **Turn access off after a restart** starts the entry with access off
on the next Core start; otherwise its saved state is retained.

The switch does not revoke a Home Assistant credential a client already holds.
Revoke that credential through Home Assistant when necessary.

### Rotating your connect URL

Use **Regenerate connect secrets now** only when you intend to change client
connection details. Update clients with the resulting URL. Do not delete and
recreate the entry as a routine update step.

## Security

- **Home Assistant sign-in (`ha_auth`)** uses the authenticated administrator's
  identity. The component retains upstream's DCR compatibility for clients that
  need registration; Core's CIMD support does not replace DCR.
- **Secret URL (`none`)** authenticates possession of the URL and executes as the
  selected administrator owner. Anonymous OAuth callbacks remain constrained by
  the configured allowlist unless an administrator explicitly changes that option.
- **Legacy OAuth (`legacy`)** retains its client ID/secret compatibility and
  executes native operations as the selected administrator owner.

Native checks active-user status and permissions at admission and again before
mutations after awaited preparation. A user context supplies attribution; it
does not replace authorization. A lost mutation response is reported honestly
and is never retried through another transport.

Legacy mode retains its administrator credential and separate listener.
Changing runtime does not silently change authentication or enable a disabled
webhook. See [SECURITY.md](../SECURITY.md) for the complete threat model.

## Relationship to the File & YAML services entry

Add **HA-MCP File & YAML Tools** only when you need the opt-in privileged file
and YAML tools. Native calls preserve that entry boundary and its permissions.
The shared registry and metadata commands are available from either entry;
they do not grant the privileged filesystem services.

The in-process server entry and the **HA-MCP File & YAML Tools** entry are two
config-entry types of the same **HA-MCP integration** (`ha_mcp_tools`). They
can be configured separately: the server works on its own, and most installs
never need the File & YAML entry. Add it only if you enable ha-mcp's opt-in file and YAML editing
tools (feature flags, off by default) — those tools call the privileged services
that entry registers, and that applies to every server type, including an
external app, Docker, or stdio server as well as the in-process server. Add or
remove it at any time from the same **Add Integration** menu (choose **HA-MCP
File & YAML Tools**); it changes nothing about how the in-process server runs.

Both entries share the integration's package requirements. A File & YAML-only
installation also installs the paired `ha-mcp` package, even when the actual
server runs in an app, Docker or another process. It does **not** need
an HA-MCP Server entry and does not start an embedded server. If installing a
shared requirement fails, neither entry can load; Home Assistant shows an
**Invalid config** persistent notification with a **Show logs** link.

## First start takes a little longer

Core may need to install the release's declared dependencies on the first
load. It uses its ordinary installer and constraints. Do not replace Core
packages manually to force an incompatible component to load.

## Troubleshooting

Check **Settings → System → Repairs** and the integration diagnostics for
version, dependency, owner or startup errors. The diagnostics redact stored
credentials. Do not post connection URLs, tokens or raw config-entry storage.

If Native refuses an unsupported Core version, install a compatible component
release or update Core. A silent switch to Legacy is not performed.
For an uncertain update, inspect the update tool's receipt and installed
version before trying again.

**The server package is broken.** If the server cannot be installed or its
code cannot be imported, the repair is titled **The HA-MCP in-process server
package could not be installed**. A common cause is another integration that
pins an older version of one of the server's dependencies: Home Assistant
installs that version for it, and only checks the server's own version
afterwards. If the repair names such an integration, update or remove it first.
If you set **ha-mcp package (advanced)**, check that value too: reinstalling a
requirement that cannot be installed fails the same way.
Then open the repair and select **Submit**: Home Assistant restarts and
reinstalls the server package before the server starts, along with any
dependency whose version no longer satisfies it.
A restart is needed because the broken package stays loaded in Home Assistant
until then.

**The integration does not load at all.** Home Assistant installs the server
build each component release pins before it loads the integration. If that
install fails (no network at startup, or a conflict with a package Home
Assistant itself needs), neither entry loads and no repair issue is filed.
Open **Notifications → Invalid config → ha_mcp_tools (Show logs)**. The log
reads `Requirements for ha_mcp_tools not found`. Fix the cause the log
names above that line, then restart Home Assistant.

**Nothing happens after updating the component.** Home Assistant loads custom
integration code at startup, so after HACS, the Marketplace or a manual copy delivers a new
version you must **restart Home Assistant** for the update to take effect.

**Skill guidance is empty after installing from a GitHub tarball.** The **ha-mcp
package (advanced)** field can install from a GitHub tarball URL, but a git
archive excludes submodules — and the bundled skill content ships as a submodule.
A tarball install therefore omits it, so the skill-guidance tools report empty
listings. Pin a PyPI version instead (every PyPI build includes the skill
content); the tarball override is only meant for quick pre-release testing.

**Reporting a problem without a working connection.** `ha_report_issue` needs a
working MCP session. Without one, open the **HA-MCP integration**
page, open the **⋮** menu of either entry and choose **Download
diagnostics** (the item appears only while the entry is loaded), then attach the
file to your issue. It lists the component version and the installed server
version, each entry's state, whether the server is running, the last startup
error, and the webhook auth mode. Secrets such as the webhook ID, the access
token or OAuth credentials are left out, and any that appear in the startup
error are replaced with `**REDACTED**`. For the package override and the
external URL, the file only says whether they are set.

**Where the logs are.** The in-process server logs into the normal Home Assistant
log (**Settings → System → Logs**, or `home-assistant.log`). Its working data
lives in `.ha_mcp/` under your Home Assistant config directory.

**The Configure screen shows only a webhook path.** If Home Assistant cannot
determine an external or internal URL, the Configure screen shows the
webhook path on its own (`/api/webhook/<webhook-id>`); prefix it with your Home
Assistant URL. Set your internal/external URLs under **Settings → System →
Network** so the full URL is shown.
