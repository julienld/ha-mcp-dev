"""One public label contract, bound to a native or legacy domain service."""

from typing import Annotated, Any, Protocol

from pydantic import Field

from ha_mcp.tools.coercion import JSON_STRING_COERCION


class Labels(Protocol):
    async def get(self, label_id: str | None = None) -> dict[str, Any]: ...
    async def set(
        self,
        name: str | None = None,
        label_id: str | None = None,
        color: str | None = None,
        icon: str | None = None,
        description: str | None = None,
        areas: str | list[str] | None = None,
    ) -> dict[str, Any]: ...
    async def remove(self, label_id: str) -> dict[str, Any]: ...


class LabelTools:
    def __init__(self, labels: Labels) -> None:
        self.labels = labels

    async def ha_config_get_label(
        self,
        label_id: Annotated[
            str | None,
            Field(
                description="ID of the label to retrieve.",
                default=None,
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Get label info - list all labels or get a specific one by ID.

        Without a label_id: Lists all Home Assistant labels with their configurations.
        With a label_id: Returns that label and, as `related`, Home Assistant's
        Related set for it: the areas, devices and entities that carry it (an
        automation, script, scene, group or person that carries it is also listed
        under its own key), the automations and scripts that target it, and the
        areas, floors, devices, config entries and integrations of the carrying
        items. A template that uses the label (for example `label_entities('x')`)
        is not listed. `related` is None, with a warning, when Home Assistant
        cannot answer; that does not mean the label is unused.

        EXAMPLES:
        - List all labels: ha_config_get_label()
        - Get specific label: ha_config_get_label("my_label_id")

        Use ha_config_set_label() to create or update labels.
        Use ha_set_entity(labels=["label1", "label2"]) to assign labels to entities,
        ha_set_device(labels=[...]) for devices, or
        ha_set_area_or_floor(kind="area", labels=[...]) for areas.
        """
        return await self.labels.get(label_id=label_id)

    async def ha_config_set_label(
        self,
        name: Annotated[
            str | None,
            Field(
                description="Display name. Required to create; omit on update to keep it.",
                default=None,
            ),
        ] = None,
        label_id: Annotated[
            str | None,
            Field(
                description="Label ID for updates.",
                default=None,
            ),
        ] = None,
        color: Annotated[
            str | None,
            Field(
                description="Color for the label (e.g., 'red', 'blue', 'green', or hex like '#FF5733'); '' or ' ' clears it",
                default=None,
            ),
        ] = None,
        icon: Annotated[
            str | None,
            Field(
                description="Material Design Icon (e.g., 'mdi:tag', 'mdi:label'); '' or ' ' clears it",
                default=None,
            ),
        ] = None,
        description: Annotated[
            str | None,
            Field(
                description="Description of the label's purpose; '' or ' ' clears it",
                default=None,
            ),
        ] = None,
        areas: Annotated[
            str | list[str] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Area IDs to apply this label to (adds the label without "
                    "removing existing ones). Omit to leave area assignments "
                    "unchanged; an empty list is a no-op (assigns nothing and "
                    "removes nothing). To clear an area's labels use "
                    "ha_set_area_or_floor(kind='area', labels=[])."
                ),
                default=None,
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Create or update a Home Assistant label.

        Creates a new label if label_id is not provided, or updates an existing
        label if label_id is provided. Labels are a cross-domain tagging system
        for entities, devices, and areas.

        EXAMPLES:
        - Create: ha_config_set_label(name="Security", color="red", icon="mdi:shield", description="Security-related devices")
        - Update: ha_config_set_label(label_id="my_label_id", color="blue")
        - Create and apply to areas: ha_config_set_label(name="Site Home", areas=["kitchen", "living_room"])

        After creating a label, use ha_set_entity(labels=["label_id"]) to assign it to entities,
        ha_set_device(labels=["label_id"]) for devices, or
        ha_set_area_or_floor(kind="area", labels=["label_id"]) for areas (replaces the area's set).
        """
        return await self.labels.set(
            name=name,
            label_id=label_id,
            color=color,
            icon=icon,
            description=description,
            areas=areas,
        )

    async def ha_config_remove_label(
        self,
        label_id: Annotated[
            str,
            Field(description="ID of the label to delete"),
        ],
    ) -> dict[str, Any]:
        """
        Delete a Home Assistant label.

        Removes the label from the label registry. Home Assistant also takes it off
        every entity, device and area that carries it. Automations and scripts that
        target the label keep the reference, which then matches nothing.

        To take a label off one item and keep it, use ha_set_entity,
        ha_set_device or ha_set_area_or_floor instead. Before deleting, call
        ha_config_get_label(label_id): its `related` lists what carries or
        targets the label, but not a template that uses it, so an empty `related`
        does not prove the label unused. The auto-backup of this call restores
        the label itself, under the id its current name gives it (a new one if
        it was renamed since it was created), not what carried it.

        EXAMPLES:
        - Delete label: ha_config_remove_label("my_label_id")

        Use ha_config_get_label() to find label IDs.
        """
        return await self.labels.remove(label_id=label_id)
