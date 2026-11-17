"""Unknown helper types retain useful validation errors on real Core."""

import pytest
from homeassistant.auth.models import User

from custom_components.ha_mcp_tools.native_backend import NativeBackend
from ha_mcp.runtime.helper_listing import HelperListingTools
from ha_mcp.runtime.helper_tools import HelperConfigTools
from ha_mcp.runtime.integration_removals import IntegrationRemovalTools
from ha_mcp.tool_api import CallContext, ToolFailure

from ._native_core_backend import backend as backend


@pytest.mark.parametrize("operation", ["list", "set", "remove"])
async def test_unknown_helper_names_the_invalid_type_and_available_choices(
    backend: NativeBackend, hass_admin_user: User, operation: str
) -> None:
    context = CallContext(hass_admin_user.id)
    helper_type = "no_such_helper"
    with pytest.raises(ToolFailure) as caught:
        if operation == "list":
            await HelperListingTools(backend, context).ha_config_list_helpers(
                helper_type
            )
        elif operation == "set":
            await HelperConfigTools(backend, context).ha_config_set_helper(
                helper_type=helper_type, name="Invalid helper"
            )
        else:
            await IntegrationRemovalTools(
                backend, context
            ).ha_remove_helpers_integrations(
                target="sensor.no_such_helper", helper_type=helper_type, confirm=True
            )
    assert caught.value.code == "VALIDATION_INVALID_PARAMETER"
    assert helper_type in str(caught.value)
    assert isinstance(caught.value.data, dict)
    error = caught.value.data["error"]
    assert isinstance(error, dict)
    suggestions = error["suggestions"]
    assert isinstance(suggestions, list)
    assert any("Storage helpers:" in item for item in suggestions)
    assert any("Helper flows on this instance:" in item for item in suggestions)
