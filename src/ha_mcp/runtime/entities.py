"""Entity discovery contract shared by native and remote execution owners."""

from typing import Annotated, Any

from pydantic import Field

from ha_mcp.tool_api import BackendTools
from ha_mcp.tools.coercion import JSON_STRING_COERCION


class EntityDiscoveryTools(BackendTools):
    async def ha_get_entity(
        self,
        entity_id: Annotated[
            str | list[str] | None,
            JSON_STRING_COERCION,
            Field(
                description="Entity ID or list of entity IDs to retrieve (e.g., 'sensor.temperature' or ['light.living_room', 'switch.porch']).",
                default=None,
            ),
        ] = None,
        unique_id: Annotated[
            str | None,
            Field(
                description=(
                    "Stable integration unique_id (entity_id is mutable, "
                    "unique_id is not). Mutually exclusive with entity_id."
                ),
                default=None,
            ),
        ] = None,
        domain: Annotated[
            str | None,
            Field(
                description="Resolver filter (unique_id mode only): restrict matches to this entity domain, e.g. 'sensor'.",
                default=None,
            ),
        ] = None,
        platform: Annotated[
            str | None,
            Field(
                description="Resolver filter (unique_id mode only): restrict matches to this integration platform, e.g. 'hue'.",
                default=None,
            ),
        ] = None,
        exposed_to: Annotated[
            str | None,
            Field(
                description=(
                    "Without entity_id and unique_id: list only the entities "
                    "exposed to this voice assistant, an ID Home Assistant knows "
                    "(today 'conversation', 'cloud.alexa', 'cloud.google_assistant'). "
                    "Adds `assistant` and its `expose_new_entities` flag; leaves "
                    "out `summary`."
                ),
                default=None,
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Get entity registry entries, or without an entity the registry settings and exposed entities.

        Returns each entry as Home Assistant's entity registry serves it
        (`config/entity_registry/get` / `get_entries`): area_id, name override,
        original_name, icon, disabled_by/hidden_by, aliases (a null alias is the
        entity's own name), labels, categories, device_class, capabilities,
        entity_category, per-domain options, platform, device_id,
        config_entry_id, unique_id and `next_name_part`. An entity with a
        device_id and no name of its own (`name: ""`, or `name: null` with no
        `original_name`) is the main entity of its device (the dialog's "Main
        entity of the device" switch). Plus the enrichment keys below.

        RESOLVER MODE:
        Pass unique_id to resolve it to its entity_id(s). Since the registry's
        unique key is (domain, platform, unique_id), the same unique_id can match
        multiple platforms — all matches are returned in entity_entries with a
        `matches` count. Narrow with domain/platform.

        When config_entry_id is non-null — e.g. for UI-created template / group /
        utility_meter / derivative helpers — pass it to
        ``ha_get_integration(entry_id=..., include_options=True)`` to read the
        helper's current config (template body, group members, etc.) without
        scanning a domain list.

        Resolved-name enrichment on an entity_id or unique_id lookup, served by the
        ha_mcp_tools component (absent without it, and a warning says which
        fields are missing and whether to install or update the component):
        `full_name` (the name Home Assistant shows, composed from the parent
        device, device and entity names; null when it has none),
        `area` (assigned area NAME, device-inherited when the entity has none),
        `floor`, and `label_names`. This tool's base `labels` carries the label ids;
        ha_search result_fields and the exposure listing's `entity_info`
        instead emit the resolved names under `labels`.

        VOICE ASSISTANT EXPOSURE:
        An entity with a registry entry keeps its exposure in the entry's
        `options` (`options.<assistant>.should_expose`; absent while nothing is
        stored); ha_set_entity(expose_to=...) sets it. An entity without a
        registry entry that has a state, or is stored as exposed, returns
        `entity_entry: null` with `exposed_to` (the assistants Home Assistant has
        stored as exposed) and
        `is_exposed_anywhere`; a list call returns such entities under
        `unregistered_entities`.

        WITHOUT entity_id AND unique_id: returns the registry-wide state:
        `settings` (Home Assistant's `config/entity_registry/settings/get`:
        `entity_id_parts`, the name parts new entity IDs are built from, null
        for Home Assistant's default) and `exposed_entities`, the entities
        exposed to at least one voice assistant as Home Assistant's
        `expose_entity/list` map, with `count` and a per-assistant `summary`
        (an assistant with no exposed entity is left out). An entity missing
        from that map is not stored as exposed: either it is stored as not
        exposed, or nothing is stored yet and Home Assistant applies its own
        default when an assistant first asks (it depends on the assistant's
        expose-new-entities flag and on the entity). When the ha_mcp_tools
        component advertises it, `entity_info` names each listed entity:
        domain, area, floor and labels (plus friendly_name and state when it
        has a state). Without it the listing has no `entity_info`, and a
        warning says whether to install or update the component.

        RELATED TOOLS: ha_set_entity() to modify these properties; ha_get_state()
        for current state/attributes; ha_search() to find entities.

        EXAMPLES:
        - Single entity: ha_get_entity("sensor.temperature")
        - Multiple entities: ha_get_entity(["light.living_room", "switch.porch"])
        - Resolve a unique_id: ha_get_entity(unique_id="00:11:22:33", domain="sensor")
        - Entities exposed to Alexa: ha_get_entity(exposed_to="cloud.alexa")
        - Registry settings and all exposed entities: ha_get_entity()
        """
        result: dict[str, Any] = await self.backend.execute(
            "entities.discover",
            {
                "entity_id": entity_id,
                "unique_id": unique_id,
                "domain": domain,
                "platform": platform,
                "exposed_to": exposed_to,
            },
            self.context,
        )
        return result
