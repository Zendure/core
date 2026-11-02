"""Tests for the Zendure binary sensor platform."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion
from zendure import UnsupportedFeatureError, ZendureConnectionError

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import build_snapshot

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform

PROBLEM = "binary_sensor.solarflow_2400_ac_problem"


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.parametrize("init_integration", [Platform.BINARY_SENSOR], indirect=True)
@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the binary sensor entities."""
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.parametrize("init_integration", [Platform.BINARY_SENSOR], indirect=True)
@pytest.mark.parametrize(
    ("active_faults", "state"),
    [
        ((), STATE_OFF),
        # DSP communication error.
        ((6,), STATE_ON),
        # DC short circuit: a code the Zendure app does not show.
        ((34,), STATE_OFF),
        # Not in the table: shown, so an unknown fault is not hidden.
        ((999,), STATE_ON),
        (None, STATE_UNAVAILABLE),
    ],
)
@pytest.mark.usefixtures("init_integration")
async def test_problem(
    hass: HomeAssistant,
    mock_read_faults: AsyncMock,
    freezer: FrozenDateTimeFactory,
    active_faults: tuple[int, ...] | None,
    state: str,
) -> None:
    """Test the problem sensor follows the visible active faults."""
    mock_read_faults.return_value = replace(
        build_snapshot(), active_faults=active_faults
    )
    await _poll(hass, freezer)

    assert hass.states.get(PROBLEM).state == state


@pytest.mark.parametrize("init_integration", [Platform.BINARY_SENSOR], indirect=True)
@pytest.mark.parametrize(
    "side_effect", [ZendureConnectionError, UnsupportedFeatureError("fault codes")]
)
@pytest.mark.usefixtures("init_integration")
async def test_problem_unavailable_on_failed_fault_read(
    hass: HomeAssistant,
    mock_read_faults: AsyncMock,
    freezer: FrozenDateTimeFactory,
    side_effect: Exception,
) -> None:
    """Test a failed fault read only makes the fault entities unavailable."""
    mock_read_faults.side_effect = side_effect
    await _poll(hass, freezer)

    assert hass.states.get(PROBLEM).state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.solarflow_2400_ac_bypass").state == (
        STATE_OFF
    )

    mock_read_faults.side_effect = None
    await _poll(hass, freezer)

    assert hass.states.get(PROBLEM).state == STATE_OFF


async def test_no_problem_entity_without_fault_codes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_zendure: MagicMock,
    mock_read_faults: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test a device that cannot report fault codes gets no fault entities."""
    mock_zendure.faults_supported = False
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not entity_registry.async_get_entity_id(
        "binary_sensor", "zendure", "TESTDEV00000001_problem"
    )
    assert not entity_registry.async_get_entity_id(
        "sensor", "zendure", "TESTDEV00000001_fault_count"
    )
    mock_read_faults.assert_not_called()
