"""One public system-health contract for Core and remote owners."""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from pydantic import Field


class HealthFacade:
    def __init__(self, get_health: Callable[..., Awaitable[dict[str, Any]]]) -> None:
        self.get_health = get_health

    async def ha_get_system_health(
        self,
        include: Annotated[
            str | None,
            Field(
                description=(
                    "Comma-separated extra sections: 'repairs' (Repair items with "
                    "the title, description and data the Repairs page shows, "
                    "active only unless include_dismissed_repairs=True); "
                    "'zha_network' (ZHA devices with radio signal summary: name, "
                    "LQI, RSSI); 'zha_network_full' (all ZHA device details; large "
                    "on 100+ device networks); 'zwave_network' (Z-Wave JS driver "
                    "connection, controller and node status); "
                    "'thread_network' (the Thread datasets Home Assistant knows, "
                    "and its OTBR border routers; no network keys); "
                    "'matter_network' (what the Matter panel reads: Core's Matter "
                    "config entry and network topology, nodes and connections "
                    "capped at 50 each); "
                    "'supervisor' (Supervisor installs: resolution info with the "
                    "unhealthy and unsupported reasons, and the Core and "
                    "Supervisor container stats); 'integration_startup' (each "
                    "integration's setup time in seconds, slowest first); "
                    "'config_check' (validate the HA configuration, the "
                    "pre-restart check ha_restart runs automatically; returns "
                    "Core's {result: valid|invalid, errors, warnings}, the "
                    "messages as one string or null; warnings alone stay "
                    "valid); 'dead_entities' "
                    "(orphaned/stale entity-registry entries: config_entry_orphans "
                    "whose owning integration instance is gone, and stale_restored "
                    "entries HA restored on startup that the loaded integration no "
                    "longer provides, each with entity_id + platform for cleanup "
                    "via ha_remove_entity; unknown-state entities and "
                    "merely-offline devices are excluded)."
                )
            ),
        ] = None,
        include_dismissed_repairs: Annotated[
            bool | None,
            Field(
                description=(
                    "Include user-dismissed/ignored repairs. Only meaningful when "
                    "'repairs' is in include. Dismiss or restore one with "
                    "ha_manage_updates(action='ignore_repair' / 'unignore_repair')."
                )
            ),
        ] = False,
    ) -> dict[str, Any]:
        """Get Home Assistant system health, including Zigbee (ZHA), Z-Wave JS, Thread and Matter networks.

        Returns health check results from integrations, system resources, and
        connectivity; available information varies by installation type and
        loaded integrations. Each domain carries the ``name`` and key ``labels``
        the System information dialog shows. Checks that Home Assistant runs in
        the background are awaited up to a deadline; one still running shows as
        pending, with a warning. Optional sections are selected with `include`.

        Not for one integration's diagnostics: use
        ha_get_integration(include_diagnostics=True). Not for themes: use
        ha_manage_theme(action='list'). Not for a single device's radio state:
        use ha_get_device. Use this tool for the state of the whole
        installation: health checks, repairs, radio networks, Supervisor,
        startup times and the configuration check.

        The result may include ``ha_mcp_update`` ``{current, latest,
        update_available}``. When update_available is true, tell the user a newer
        ha-mcp release is available (with ``python_required``, give ``upgrade_command``).

        EXAMPLES:
        - ha_get_system_health(include="repairs,zha_network,zwave_network,config_check")
        - ha_get_system_health(include="supervisor,integration_startup")
        """
        return await self.get_health(
            include=include, include_dismissed_repairs=include_dismissed_repairs
        )
