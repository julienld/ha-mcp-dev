"""One helper write signature and orchestration for both backend families."""

import logging
from typing import Annotated, Any, Literal

from pydantic import Field

from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.tool_api import ToolFailure
from ha_mcp.tool_api.parameters import BestPracticeKeyParam
from ha_mcp.tools.coercion import JSON_STRING_COERCION, parse_string_list_param

from .errors import raise_failure
from .helper_payload import storage_fields
from .helper_schema import (
    _SIMPLE_CONFIG_KEYS_DESCRIPTION,
    SIMPLE_HELPER_TYPES,
    StorageHelperType,
)
from .helper_storage import HelperStorageTools
from .helper_validation import _reject_flow_params_on_storage_helper
from .validation import clear_or_keep

_LOGGER = logging.getLogger(__name__)


class HelperConfigTools(HelperStorageTools):
    async def ha_config_set_helper(
        self,
        helper_type: Annotated[
            StorageHelperType | Literal["config_subentry"] | str,
            Field(description="Type of helper to create or update."),
        ],
        name: Annotated[
            str | None,
            Field(
                description=(
                    "Display name. Home Assistant decides which SIMPLE helper "
                    "types need one to be created; optional on an update. "
                    "Creating a FLOW helper, it answers the "
                    "form's `name` field when the form has one and config "
                    "sets none; a FLOW update does not use it (rename the "
                    "entity with ha_set_entity). Not used by config_subentry."
                ),
                default=None,
            ),
        ] = None,
        helper_id: Annotated[
            str | None,
            Field(
                description=(
                    "The helper's storage id ('my_button'), not the name of its "
                    "entity, or its full entity_id ('input_button.my_button'); "
                    "for a FLOW helper its config entry id. Omit to create a "
                    "new helper."
                ),
                default=None,
            ),
        ] = None,
        entry_id: Annotated[
            str | None,
            Field(
                description=(
                    "Parent config entry ID when helper_type='config_subentry'. "
                    "Use ha_get_integration() to find entry IDs."
                ),
                default=None,
            ),
        ] = None,
        subentry_type: Annotated[
            str | None,
            Field(
                description=(
                    "Integration-defined subentry type when "
                    "helper_type='config_subentry'."
                ),
                default=None,
            ),
        ] = None,
        subentry_id: Annotated[
            str | None,
            Field(
                description=(
                    "Existing config subentry ID to reconfigure when "
                    "helper_type='config_subentry'."
                ),
                default=None,
            ),
        ] = None,
        show_advanced_options: Annotated[
            bool,
            Field(
                description=(
                    "When helper_type='config_subentry', ask older Home "
                    "Assistant versions to expose advanced flow options. No-op "
                    "on HA 2026.6+; pending removal before HA 2027.6."
                ),
                default=False,
            ),
        ] = False,
        icon: Annotated[
            str | None,
            Field(
                description="Material Design Icon (e.g., 'mdi:bell'); '' or ' ' clears it, except a zone's stored icon, which Home Assistant keeps on update as the zone dialog does: it can be changed but not removed. A storage helper's icon goes into its stored config when Home Assistant's schema for the type has an icon field, as the helper's own dialog stores it, and the entity registry is left alone; otherwise (person, tag, or another type without the ha_mcp_tools component) it goes into the entity registry. An icon override in the entity registry is set or cleared with ha_set_entity. Restoring a storage helper's automatic backup also puts back its registry icon, unless the backup predates registry icons being recorded; a flow helper's backup holds no icon, so its restore does not set one",
                default=None,
            ),
        ] = None,
        area_id: Annotated[
            str | None,
            Field(
                description="Area ID for the helper; '' or ' ' clears it", default=None
            ),
        ] = None,
        labels: Annotated[
            str | list[str] | None,
            JSON_STRING_COERCION,
            Field(description="Labels to categorize the helper", default=None),
        ] = None,
        category: Annotated[
            str | None,
            Field(
                description="Category ID for this helper (ha_config_get_category(scope='helpers') lists them, ha_config_set_category() creates one); '' or ' ' clears it.",
                default=None,
            ),
        ] = None,
        config: Annotated[
            dict[str, Any] | list[dict[str, Any]] | None,
            JSON_STRING_COERCION,
            Field(
                description=(
                    "Type-specific fields. On update it is a patch: a field "
                    "you omit keeps its current value, and a SIMPLE type's "
                    "field set to null is removed. SIMPLE types take "
                    f"these keys: {_SIMPLE_CONFIG_KEYS_DESCRIPTION} "
                    "FLOW types and config_subentry: the answers to the form "
                    "the flow is at, under the form's own field names (a "
                    "section's fields nested under the section's name). On an "
                    "update a field you omit is sent as the form shows it "
                    "(its `current` value); a field set to null is left "
                    "empty. Home Assistant validates the answer. A list "
                    "answers several forms: one object per form, in the "
                    "order Home Assistant asks for them."
                ),
                default=None,
            ),
        ] = None,
        menu_choice: Annotated[
            str | None,
            Field(
                description=(
                    "FLOW types and config_subentry: the option to pick at a "
                    "menu step (template and group open with one)."
                ),
                default=None,
            ),
        ] = None,
        flow_id: Annotated[
            str | None,
            Field(
                description=(
                    "Continue an open flow: the flow_id a previous call "
                    "returned, with the same helper_type and helper_id (or "
                    "entry_id, subentry_type and subentry_id)."
                ),
                default=None,
            ),
        ] = None,
        abort: Annotated[
            bool,
            Field(
                description="With flow_id: end the open flow without saving.",
                default=False,
            ),
        ] = False,
        wait: Annotated[
            bool,
            Field(
                description="Wait for helper entity to be queryable before returning. Set to False "
                "for bulk operations.",
                default=True,
            ),
        ] = True,
        action: Annotated[
            Literal["create", "update"] | None,
            Field(
                description=(
                    "Explicit intent: 'create' a new helper or 'update' an existing one. "
                    "Pass it so a helper_id typo fails as 'helper not found' instead of "
                    "creating a helper."
                ),
                default=None,
            ),
        ] = None,
        MandatoryBPS: Annotated[
            bool,
            Field(default=True),
        ] = True,
        # BestPracticeKey (#1779): consumed by StrictBpsMiddleware, never read
        # here — see strict_bps.py for the declaration contract.
        BestPracticeKey: BestPracticeKeyParam = None,
    ) -> dict[str, Any]:
        """Create or update Home Assistant helpers: storage types, every helper
        flow HA lists, and config subentries.

        MUST call ha_get_skill_guide OR refer to your locally installed skills first.
        ``helper-selection.md`` ships under ``skill_content`` by default.

        SIMPLE types, written in one call: input_boolean, input_button,
        input_select, input_number, input_text, input_datetime, counter, timer, schedule,
        zone, person, tag.

        FLOW types: every helper flow Home Assistant lists, read from it at
        call time — template, group, utility_meter, derivative, min_max,
        threshold, integration, statistics, trend, ... and custom helper
        integrations. Creating one runs its config flow; `helper_id` (the
        config entry id) runs its options flow instead.
        Do not create `otp` here although Home Assistant lists it: the user sets
        it up in the HA UI, since its secret is a credential they enroll in an
        authenticator app.

        CONFIG_SUBENTRY type: pass `entry_id` and `subentry_type`; with
        `subentry_id` the subentry's reconfigure flow runs, without it its
        create flow.

        Flows, one step per call, as the HA UI runs them: a call answers the
        step the flow is at and returns Home Assistant's next answer. A form
        comes back with its fields (type, default, current value, Home
        Assistant's help text) and flow_id; a menu with menu_options. Answer
        with flow_id and config (a form) or menu_choice (a menu); flow_id alone
        returns the step again, and flow_id with abort=True ends the flow.
        Without flow_id a new flow starts: menu_choice answers its opening
        menu and config the form after it, so a one-form helper is created or
        updated in one call; without config the call returns the form, and
        its later_forms when the helper has more than one (statistics,
        history_stats, generic_thermostat, ...). With a config list the call
        answers form after form and returns at the first one Home Assistant
        rejects, or once the answers run out. A rejected form is an error
        with Core's text, and the flow stays open to correct it. Nothing is
        saved until the flow finishes.

        WHEN NOT TO USE:
        - An integration that is not a helper: ha_set_integration.
        - Removing a helper: ha_remove_helpers_integrations.
        - Renaming a flow helper's entity, or its registry settings alone:
          ha_set_entity.

        Behavior:
        - A SIMPLE update preserves type-specific fields not re-passed (a rename
          never wipes initial/icon/etc.).
        - Omitted `action`: update when `helper_id` (for a config subentry,
          `subentry_id`) is given, else create.
        - area_id, labels, category and icon are applied to a flow helper's
          entities by the call that finishes the flow.
        - A progress step (Home Assistant working in the background) is waited
          out for up to 120 s. When Home Assistant does not answer a submit,
          the error carries status applied_but_unverified: check the helper
          before retrying.

        EXAMPLES:
        - input_number: ha_config_set_helper(helper_type="input_number", name="Target", config={"min": 0, "max": 100, "step": 5})
        - template sensor: ha_config_set_helper(helper_type="template", menu_choice="sensor", config={"name": "Room Temp", "state": "{{ states('sensor.x')|float }}", "unit_of_measurement": "°C"})
        - group: ha_config_set_helper(helper_type="group", menu_choice="light", config={"name": "Kitchen Lights", "entities": ["light.a", "light.b"]})
        - see a form first: ha_config_set_helper(helper_type="statistics"), then answer it: ha_config_set_helper(helper_type="statistics", flow_id="...", config={...})
        - several forms in one call: ha_config_set_helper(helper_type="statistics", config=[{"name": "Temp Mean", "entity_id": "sensor.temp"}, {"state_characteristic": "mean"}, {"sampling_size": 20}])
        - update one option: ha_config_set_helper(helper_type="group", helper_id="01HXYZ...", config={"hide_members": true})
        - config subentry: ha_config_set_helper(helper_type="config_subentry", entry_id="01HXYZ...", subentry_type="conversation", config={"name": "Local agent", "model": "gemma3:27b"})
        """
        try:
            area_id = clear_or_keep(area_id, "area_id")
            icon = clear_or_keep(icon, "icon")
            category = clear_or_keep(category, "category")
            menu_choice, flow_id = menu_choice or None, flow_id or None
            if helper_type == "config_subentry":
                return await self._set_config_subentry(
                    action,
                    entry_id,
                    subentry_type,
                    subentry_id,
                    config,
                    MandatoryBPS,
                    flow_id=flow_id,
                    menu_choice=menu_choice,
                    abort=abort,
                    show_advanced_options=show_advanced_options,
                )

            await self._require_helper_type(helper_type)
            action = await self._validate_action(action, helper_id, helper_type)
            async with self._schema_context(helper_type, action):
                if helper_type not in SIMPLE_HELPER_TYPES:
                    return await self._flow_helper(
                        helper_type,
                        name,
                        helper_id,
                        config,
                        area_id,
                        labels,
                        category,
                        wait,
                        icon=icon,
                        action=action,
                        MandatoryBPS=MandatoryBPS,
                        flow_id=flow_id,
                        menu_choice=menu_choice,
                        abort=abort,
                    )
                _reject_flow_params_on_storage_helper(
                    helper_type,
                    {
                        "flow_id": flow_id,
                        "menu_choice": menu_choice,
                        "abort": abort or None,
                    },
                )
                name, icon, fields = storage_fields(helper_type, config, name, icon)
                unchecked = None
                if action == "create" and self._check_create_name:
                    unchecked = await self._check_name_collision(helper_type, name)
                try:
                    labels = parse_string_list_param(labels, "labels")
                except ValueError as error:
                    raise_failure(
                        create_error_response(
                            ErrorCode.VALIDATION_INVALID_PARAMETER,
                            f"Invalid list parameter: {error}",
                        )
                    )
                await self._validate_registry_ids(
                    area_id, labels, {"helpers": category}, fail_closed=True
                )
                if action == "create":
                    created = await self._create_simple(
                        helper_type,
                        name,
                        icon,
                        area_id,
                        labels,
                        category,
                        wait,
                        MandatoryBPS,
                        fields,
                    )
                    if unchecked:
                        created.setdefault("warnings", []).append(unchecked)
                    return created
                assert helper_id is not None
                return await self._update_simple(
                    helper_type,
                    helper_id,
                    helper_id,
                    name,
                    icon,
                    area_id,
                    labels,
                    category,
                    wait,
                    MandatoryBPS,
                    fields,
                )
        except ToolFailure:
            raise
        except Exception as error:
            _LOGGER.debug("Mapping helper failure", exc_info=True)
            return self._map_helper_error(error, action, helper_type)
