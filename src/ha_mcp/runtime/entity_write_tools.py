"""The complete entity-write contract, independent of the execution owner."""

from typing import Annotated, Any, Literal, Protocol

from pydantic import Field

from ha_mcp.runtime.validation import WHITESPACE_CLEARS_NOTE
from ha_mcp.tools.coercion import JSON_STRING_COERCION


class EntityWrites(Protocol):
    async def set(
        self, entity_id: str | list[str] | None, **arguments: Any
    ) -> dict[str, Any]: ...


class EntityWriteTools:
    def __init__(self, entities: EntityWrites) -> None:
        self.entities = entities

    async def ha_set_entity(
        self,
        entity_id: Annotated[
            str | list[str] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Entity ID or list of entity IDs to update. Omit only for the "
                    "registry-wide expose_new_entities and entity_id_parts."
                ),
                default=None,
            ),
        ] = None,
        area_id: Annotated[
            str | None,
            Field(
                description=(
                    "Area/room ID to assign the entity to. Use empty string '' to "
                    "unassign from current area. " + WHITESPACE_CLEARS_NOTE
                ),
                default=None,
            ),
        ] = None,
        name: Annotated[
            str | None,
            Field(
                description=(
                    "The entity's own name part, not the full name. Use empty string '' to remove "
                    "the custom name and revert to default. " + WHITESPACE_CLEARS_NOTE
                ),
                default=None,
            ),
        ] = None,
        use_device_name: Annotated[
            bool | None,
            Field(
                description=(
                    "The entity dialog's 'Main entity of the device' switch. True "
                    "names the entity after its device, following device renames, "
                    "and like the dialog moves it from its own area to the "
                    "device's. An entity without a name of its own already is the "
                    "main entity and is left as is. False restores the "
                    "integration's default name. Omit to leave it as is; not "
                    "combinable with name."
                ),
                default=None,
            ),
        ] = None,
        icon: Annotated[
            str | None,
            Field(
                description=(
                    "Icon for the entity (e.g., 'mdi:thermometer'). Use empty string "
                    "'' to remove custom icon. " + WHITESPACE_CLEARS_NOTE
                ),
                default=None,
            ),
        ] = None,
        device_class: Annotated[
            str | None,
            Field(
                description=(
                    "Override the entity's display device class — what the HA UI's 'Show "
                    "As' dropdown writes. Use empty string '' to clear the override and "
                    "fall back to the integration default. Examples: 'window', 'door', "
                    "'motion' for binary_sensor; 'temperature', 'humidity' for sensor. "
                    + WHITESPACE_CLEARS_NOTE
                ),
                default=None,
            ),
        ] = None,
        options: Annotated[
            dict[str, dict[str, Any]] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Per-domain entity registry options (e.g. sensor 'display_precision', "
                    "weather 'forecast_type'). Pass a dict mapping domain to a sub-dict, "
                    'e.g. {"sensor": {"display_precision": 2}}. '
                    "For 'Show As' use device_class; for "
                    "voice-assistant exposure use expose_to, not "
                    "options.<assistant>.should_expose."
                ),
                default=None,
            ),
        ] = None,
        enabled: Annotated[
            bool | None,
            Field(
                description=(
                    "True to enable the entity, False to disable it. WARNING: "
                    "enabled=False is a registry-level disable, not 'turning off': "
                    "the entity leaves the state machine, the UI, dashboards and "
                    "automations. Re-enabling returns Home Assistant's own answer: "
                    "require_restart, or reload_delay (seconds until it reloads "
                    "the integration itself)."
                ),
                default=None,
            ),
        ] = None,
        hidden: Annotated[
            bool | None,
            Field(
                description="True to hide the entity from UI, False to show it.",
                default=None,
            ),
        ] = None,
        aliases: Annotated[
            str | list[str | None] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "List of voice assistant aliases for the entity (replaces existing "
                    "aliases). A null entry is the entity's own name (HA's 'use entity "
                    "name' switch); it is kept automatically unless your list already "
                    "contains null. To turn that switch off or on, use "
                    "use_entity_name_alias."
                ),
                default=None,
            ),
        ] = None,
        use_entity_name_alias: Annotated[
            bool | None,
            Field(
                description=(
                    "HA's 'use entity name' voice-alias switch. True keeps the entity's "
                    "own name answering in Assist, False turns it off so only the "
                    "aliases match. Omit to leave it as is. Works with or without "
                    "aliases."
                ),
                default=None,
            ),
        ] = None,
        categories: Annotated[
            dict[str, str | None] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Category assignment as a dict mapping scope to category_id. "
                    'Example: {"automation": "category_id_here"}. '
                    'Use null value to clear: {"automation": null}.'
                ),
                default=None,
            ),
        ] = None,
        labels: Annotated[
            str | list[str] | None,
            JSON_STRING_COERCION,
            Field(
                description="List of label IDs for the entity. Behavior depends on label_operation parameter. Use [] with label_operation='set' to clear.",
                default=None,
            ),
        ] = None,
        label_operation: Annotated[
            Literal["set", "add", "remove"],
            Field(
                description="How to apply labels: 'set' replaces all labels, 'add' adds to existing, 'remove' removes specified labels.",
                default="set",
            ),
        ] = "set",
        expose_to: Annotated[
            dict[str, bool] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Control voice assistant exposure. Pass a dict mapping assistant IDs to booleans. "
                    "Assistant IDs Home Assistant knows, today 'conversation' (Assist), 'cloud.alexa' "
                    "and 'cloud.google_assistant'; it refuses any other name before any change is sent to it. "
                    'Example: {"conversation": true, "cloud.alexa": false}. '
                    "An entity without a registry entry is written under the id Home "
                    "Assistant reads it by and answers with entity_entry null; an id "
                    "Home Assistant does not know is refused before anything is written."
                ),
                default=None,
            ),
        ] = None,
        expose_new_entities: Annotated[
            dict[str, bool] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Registry-wide, no entity_id: each assistant's 'Expose new "
                    "entities' switch, as a dict mapping assistant IDs to booleans "
                    '(e.g. {"cloud.alexa": false}). Home Assistant refuses an '
                    "assistant it does not know before any change is sent."
                ),
                default=None,
            ),
        ] = None,
        entity_id_parts: Annotated[
            list[str] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Registry-wide, no entity_id: the name parts new entity IDs "
                    "are built from, in order. Home Assistant judges the list; "
                    "today it takes 'area', 'floor', 'parent_device', 'device' "
                    "and 'entity', and requires 'device' and 'entity'. [] "
                    "restores Home Assistant's default."
                ),
                default=None,
            ),
        ] = None,
        new_entity_id: Annotated[
            str | None,
            Field(
                description=(
                    "New entity ID to rename to (e.g., 'light.new_name'); the domain "
                    "must stay the same. 'auto' takes the ID Home Assistant would "
                    "generate for the entity now, like the UI's Restore entity ID "
                    "(no rename when the entity already has it)."
                ),
                default=None,
            ),
        ] = None,
        new_device_name: Annotated[
            str | None,
            Field(
                description=(
                    "New display name for the associated device. An entity_id "
                    "Home Assistant does not know is refused; an entity without a "
                    "device gets a warning. Empty or whitespace-only never changes "
                    "the device name: it is "
                    "reported under warnings when other fields are given and is an "
                    "error when it is the only update. To clear the device name use "
                    "ha_set_device(name='')."
                ),
                default=None,
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Update entity registry entries, or without entity_id the registry-wide settings.

        Allows modifying entity metadata such as area assignment, display name,
        icon, "Show As" device class override, per-domain registry options,
        enabled/disabled state, visibility, aliases, labels, voice assistant
        exposure, and entity_id rename in a single call.

        BULK OPERATIONS:
        When entity_id is a list, only labels, expose_to, and categories parameters are supported.
        Other parameters (area_id, name, use_device_name, icon, device_class, options, enabled, hidden, aliases, use_entity_name_alias, new_entity_id, new_device_name) require single entity.

        SHOW AS / DEVICE CLASS: a device_class change applies instantly, no reload
        needed.

        REGISTRY OPTIONS: multi-domain options are sent as separate registry
        updates because HA's WS schema requires options_domain + options to be
        paired one domain at a time.

        ENTITY ID RENAME: Voice exposure settings are preserved automatically.

        WARNING: Renaming an entity_id does NOT update references in automations,
        scripts, templates, or dashboards. All consumers of the old entity_id must
        be updated manually — HA does not propagate the rename automatically.

        Rename limitation: an entity without a unique ID cannot be renamed.

        REGISTRY-WIDE SETTINGS: for the parameters sent, the reply has Home
        Assistant's `settings`, the `expose_new_entities` written, and the values
        they replace
        (`previous_settings`, `previous_expose_new_entities`). ha_get_entity()
        reads them.

        Use ha_search() or ha_get_device() to find entity IDs.
        Use ha_config_get_label() to find available label IDs.

        EXAMPLES:
        - Assign to area: ha_set_entity("sensor.temp", area_id="living_room")
        - Set Show As: ha_set_entity("binary_sensor.zone_10", device_class="window")
        - Set sensor precision: ha_set_entity("sensor.power", options={"sensor": {"display_precision": 2}})
        - Stop exposing new entities to Alexa: ha_set_entity(expose_new_entities={"cloud.alexa": false})
        - Rename entity and device: ha_set_entity("light.old", new_entity_id="light.new", new_device_name="New Lamp")
        - Add labels to multiple: ha_set_entity(["light.a", "light.b"], labels=["new"], label_operation="add")
        - Expose to Alexa: ha_set_entity("light.lamp", expose_to={"cloud.alexa": True})

        AUTOMATIONS AND SCRIPTS:
        For automations and scripts, enabled=False is blocked. For automations,
        use ha_config_set_automation(entity_id="automation.xxx", enabled=False)
        (or enabled=True to re-enable).
        For scripts, ha_config_set_script(script_id="script.xxx", run="stop")
        only stops a currently running execution; it does not disable the script.
        Home Assistant has no script runtime enable/disable service.
        """
        return await self.entities.set(
            entity_id=entity_id,
            area_id=area_id,
            name=name,
            use_device_name=use_device_name,
            icon=icon,
            device_class=device_class,
            options=options,
            enabled=enabled,
            hidden=hidden,
            aliases=aliases,
            use_entity_name_alias=use_entity_name_alias,
            categories=categories,
            labels=labels,
            label_operation=label_operation,
            expose_to=expose_to,
            expose_new_entities=expose_new_entities,
            entity_id_parts=entity_id_parts,
            new_entity_id=new_entity_id,
            new_device_name=new_device_name,
        )
