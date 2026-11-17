"""Client catalog refresh guidance shared by Native and Legacy validation."""

from collections.abc import Sequence

from ha_mcp.renamed_tools import CLIENT_TOOL_LIST_REFRESH_STEPS


def _stale_tool_list_hint(names: Sequence[str]) -> str:
    """Suggestion for undeclared arguments the client's own tool list may show.

    Conditional on purpose: an agent can also invent a name, as agents sent
    ``entity_id`` before any tool declared it (#2877), and then there is no
    stale list to refresh.
    """
    listed = ", ".join(f"`{name}`" for name in names)
    them = "them" if len(names) > 1 else "it"
    return (
        f"If your tool list shows {listed} on this tool, that list is a stale "
        f"copy from before an ha-mcp update renamed or removed {them}, "
        "not a server bug. Ask the user to reconnect this MCP server in their "
        f"client ({CLIENT_TOOL_LIST_REFRESH_STEPS}), then start a new "
        "conversation."
    )
