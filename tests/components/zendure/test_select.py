"""Tests for the Zendure select platform."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import build_snapshot

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform

pytestmark = pytest.mark.parametrize(
    "init_integration", [Platform.SELECT], indirect=True
)


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the select entities."""
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("entity_id", "option", "key", "raw"),
    [
        ("select.solarflow_2400_ac_ac_mode", "input", "acMode", 1),
        ("select.solarflow_2400_ac_off_grid_mode", "eco", "gridOffMode", 1),
        ("select.solarflow_2400_ac_grid_feed_in", "allow", "gridReverse", 1),
    ],
)
async def test_select_option(
    hass: HomeAssistant,
    mock_zendure: MagicMock,
    entity_id: str,
    option: str,
    key: str,
    raw: int,
) -> None:
    """Test selecting an option writes its raw code."""
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option},
        blocking=True,
    )

    mock_zendure.async_set.assert_awaited_once_with(key, raw)


@pytest.mark.usefixtures("init_integration")
async def test_unknown_code(
    hass: HomeAssistant,
    mock_read: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test an unrecognized mode code shows as unknown."""
    snapshot = build_snapshot()
    mock_read.return_value = replace(
        snapshot, properties={**snapshot.properties, "acMode": 7}
    )
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("select.solarflow_2400_ac_ac_mode").state == STATE_UNKNOWN
