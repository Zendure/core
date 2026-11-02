"""Tests for the Zendure switch platform."""

from unittest.mock import MagicMock

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry, snapshot_platform

pytestmark = pytest.mark.parametrize(
    "init_integration", [Platform.SWITCH], indirect=True
)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the switch entities."""
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("service", "raw"), [(SERVICE_TURN_ON, 1), (SERVICE_TURN_OFF, 0)]
)
async def test_turn_on_off(
    hass: HomeAssistant, mock_zendure: MagicMock, service: str, raw: int
) -> None:
    """Test switching writes the property through the library."""
    await hass.services.async_call(
        SWITCH_DOMAIN,
        service,
        {ATTR_ENTITY_ID: "switch.solarflow_2400_ac_indicator_light"},
        blocking=True,
    )

    mock_zendure.async_set.assert_awaited_once_with("lampSwitch", raw)
