"""Category authoring shares orchestration across remote and Core owners."""

import logging
from typing import Annotated, Any, NoReturn

from pydantic import Field

from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.tool_api import ToolFailure

from .error_text import core_error_message
from .errors import raise_classified, raise_core_refusal, raise_failure
from .labels import CategoryDiscoveryTools
from .registry_write_context import RegistryWriteContext
from .validation import (
    clearable_value,
    refuse_blank_name,
    validate_identifier_not_empty,
)

logger = logging.getLogger(__name__)


class CategoryWriteTools(CategoryDiscoveryTools, RegistryWriteContext):
    def _map_category_write_error(
        self, error: Exception, context: dict[str, Any], suggestions: list[str]
    ) -> NoReturn:
        raise_classified(error, context, suggestions=suggestions)

    async def _category_change(
        self, action: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._registry_change(
            "category",
            action,
            data,
            "ha_config_remove_category"
            if action == "delete"
            else "ha_config_set_category",
        )

    async def ha_config_set_category(
        self,
        scope: Annotated[
            str,
            Field(
                description="Domain scope for the category (e.g., 'automation', 'script', 'scene', 'helpers').",
            ),
        ],
        name: Annotated[
            str | None,
            Field(
                description="Display name. Required to create; omit on update to keep it.",
                default=None,
            ),
        ] = None,
        category_id: Annotated[
            str | None,
            Field(
                description="Category ID for updates.",
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
    ) -> dict[str, Any]:
        """
        Create or update a Home Assistant category.

        Creates a new category if category_id is not provided, or updates an existing category if category_id is provided.

        Categories are domain-scoped organizational groups for automations, scripts,
        scenes, and helpers. Unlike labels (which are cross-domain), categories are
        specific to a single domain scope.

        EXAMPLES:
        - Create automation category: ha_config_set_category(scope="automation", name="Lighting")
        - Create with icon: ha_config_set_category(scope="automation", name="Security", icon="mdi:shield")
        - Update category: ha_config_set_category(scope="automation", category_id="my_category_id", name="Updated Name")

        After creating a category, use ha_set_entity(categories={"automation": "category_id"}) to assign it.
        """
        try:
            # ``None`` stays the documented "create-new" sentinel; explicit
            # empty/whitespace is rejected so the create/update discriminator
            # below cannot silently route an intended update to create.
            if category_id is not None:
                validate_identifier_not_empty(
                    category_id,
                    "category_id",
                    suggestions=[
                        "Omit category_id entirely to create a new category",
                        "Pass a valid category_id to update an existing category",
                    ],
                    context={"action": "set", "scope": scope, "name": name},
                )
            refuse_blank_name(
                name, {"action": "set", "scope": scope, "category_id": category_id}
            )
            action = "update" if category_id else "create"

            message: dict[str, Any] = {
                "type": f"config/category_registry/{action}",
                "scope": scope,
            }
            if action == "update":
                message["category_id"] = category_id
            if name is not None:
                message["name"] = name
            if icon is not None:
                message["icon"] = clearable_value(icon, "icon")

            result = await self._category_change(
                action, {key: value for key, value in message.items() if key != "type"}
            )

            if result.get("success"):
                category_data = result.get("result", {})
                action_past = "created" if action == "create" else "updated"
                return {
                    "success": True,
                    "category_id": category_data.get("category_id"),
                    "category_data": category_data,
                    "scope": scope,
                    "message": f"Successfully {action_past} category: {category_data.get('name')}",
                }
            context = {"name": name, "scope": scope, "category_id": category_id}
            # Core answers an unknown id with the generic ``invalid_info`` code, so
            # its exact message is what tells it apart from a refused name (which
            # quotes the caller's name and could contain any text).
            reason = core_error_message(result.get("error", ""))
            if reason == "Category ID doesn't exist":
                raise_failure(
                    create_error_response(
                        ErrorCode.RESOURCE_NOT_FOUND,
                        f"Category {category_id!r} not found in scope {scope!r}: {reason}",
                        context={**context, "ha_error_code": result.get("error_code")},
                        suggestions=[
                            f"Use ha_config_get_category('{scope}') without category_id to see all categories",
                            "Check the scope: a category exists only in the scope it was created in",
                        ],
                    )
                )
            suggestions = [
                f"Use ha_config_get_category('{scope}') to see the existing categories and their IDs"
            ]
            if action == "create" and name is None:
                suggestions.insert(
                    0, "Pass name to create a category, or category_id to update one"
                )
            raise_core_refusal(
                f"Failed to {action} category",
                result,
                context=context,
                suggestions=suggestions,
            )

        except ToolFailure:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error setting category {name!r}: {e}")
            self._map_category_write_error(
                e,
                context={"name": name, "scope": scope, "category_id": category_id},
                suggestions=[
                    "Check Home Assistant connection",
                    "Verify the category name is valid",
                    "For updates, verify the category_id exists using ha_config_get_category()",
                ],
            )
            return None  # unreachable: exception_to_structured_error always raises
        return None  # py/mixed-returns: explicit terminal; error handlers above always raise (NoReturn), unreachable

    async def ha_config_remove_category(
        self,
        scope: Annotated[
            str,
            Field(
                description="Domain scope for the category (e.g., 'automation', 'script', 'scene', 'helpers').",
            ),
        ],
        category_id: Annotated[
            str,
            Field(description="ID of the category to delete"),
        ],
    ) -> dict[str, Any]:
        """
        Delete a Home Assistant category.

        Removes the category from the category registry for the given scope, and
        from every entity in that scope that had it. The auto-backup of this call
        restores the category itself, under a new id, not the entities that had it.

        To move one entity to another category or out of its category and keep the
        category, use ha_set_entity(categories=...) instead.

        EXAMPLES:
        - Delete category: ha_config_remove_category("automation", "my_category_id")

        Use ha_config_get_category() to find category IDs.
        """
        try:
            # Empty/whitespace would surface as a misleading HA delete-failure.
            validate_identifier_not_empty(
                category_id,
                "category_id",
                suggestions=[
                    "Pass a valid category_id (use ha_config_get_category() to list)",
                ],
                context={"action": "remove", "scope": scope},
            )
            message: dict[str, Any] = {
                "type": "config/category_registry/delete",
                "scope": scope,
                "category_id": category_id,
            }

            result = await self._category_change(
                "delete",
                {key: value for key, value in message.items() if key != "type"},
            )

            if result.get("success"):
                return {
                    "success": True,
                    "category_id": category_id,
                    "scope": scope,
                    "message": f"Successfully deleted category: {category_id}",
                }
            context = {"category_id": category_id, "scope": scope}
            # Same exact-text test as the set tool: ``invalid_info`` is generic.
            if (
                core_error_message(result.get("error", ""))
                == "Category ID doesn't exist"
            ):
                raise_failure(
                    create_error_response(
                        ErrorCode.RESOURCE_NOT_FOUND,
                        f"Category not found: {category_id}",
                        context={**context, "ha_error_code": result.get("error_code")},
                        suggestions=[
                            f"Use ha_config_get_category('{scope}') without category_id to see all categories",
                        ],
                    )
                )
            raise_core_refusal("Failed to delete category", result, context=context)

        except ToolFailure:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error removing category {category_id!r}: {e}")
            self._map_category_write_error(
                e,
                context={"category_id": category_id, "scope": scope},
                suggestions=[
                    "Check Home Assistant connection",
                    "Verify the category_id exists using ha_config_get_category()",
                ],
            )
            return None  # unreachable: exception_to_structured_error always raises
        return None  # py/mixed-returns: explicit terminal; error handlers above always raise (NoReturn), unreachable
