"""An explicit Core exposure preference bypasses both default lookups."""

from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.ha_mcp_tools import core_assist
from custom_components.ha_mcp_tools.core_assist import _assist_should_expose


async def test_explicit_override_avoids_default_reads(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = entity_registry.async_get_or_create("light", "test", "override")
    entity_registry.async_update_entity_options(
        entry.entity_id, "conversation", {"should_expose": True}
    )
    expose_new = Mock(side_effect=AssertionError("must not be consulted"))
    default_exposed = Mock(side_effect=AssertionError("must not be consulted"))
    monkeypatch.setattr(core_assist, "_assist_expose_new_entities", expose_new)
    monkeypatch.setattr(core_assist, "_assist_default_exposed", default_exposed)

    assert _assist_should_expose(hass, entry.entity_id) is True
    expose_new.assert_not_called()
    default_exposed.assert_not_called()
