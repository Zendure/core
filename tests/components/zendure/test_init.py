"""Integration setup tests for the Zendure integration."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from zendure import ZendureConnectionError, ZendureProtocolError

from homeassistant.components.zendure.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import BATTERY_SERIAL_NUMBER, SERIAL_NUMBER, build_snapshot

from tests.common import MockConfigEntry, async_fire_time_changed


async def test_load_unload_config_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_zendure: MagicMock,
) -> None:
    """Test the Zendure configuration entry loading and unloading."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_zendure.close.assert_awaited_once()


@pytest.mark.usefixtures("mock_zendure")
@pytest.mark.parametrize("side_effect", [ZendureConnectionError, ZendureProtocolError])
async def test_config_entry_not_ready(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read: AsyncMock,
    side_effect: Exception,
) -> None:
    """Test the Zendure configuration entry not ready."""
    mock_read.side_effect = side_effect
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_devices(
    device_registry: dr.DeviceRegistry, init_integration: MockConfigEntry
) -> None:
    """Test the device and its battery pack are registered and linked."""
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SERIAL_NUMBER), init_integration.entry_id
    )
    assert device
    assert device.manufacturer == "Zendure"
    assert device.model == "SolarFlow 2400 AC+"
    assert device.model_id == "solarFlow2400AC+"
    assert device.serial_number == SERIAL_NUMBER

    battery = device_registry.async_get_device_by_identifier(
        (DOMAIN, BATTERY_SERIAL_NUMBER), init_integration.entry_id
    )
    assert battery
    assert battery.via_device_id == device.id


async def test_device_unavailable_and_recovers(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_read: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test entities become unavailable on a failed poll and then recover."""
    entity_id = "sensor.solarflow_2400_ac_battery"
    assert hass.states.get(entity_id).state == "57"

    mock_read.side_effect = ZendureConnectionError
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    mock_read.side_effect = None
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "57"


async def test_battery_added_and_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_read: AsyncMock,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test battery packs are added and removed as the device reports them."""
    snapshot = build_snapshot()
    extra = replace(snapshot.batteries[0], serial_number="TESTBAT00000002")
    mock_read.return_value = replace(snapshot, batteries=(*snapshot.batteries, extra))
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, "TESTBAT00000002"), init_integration.entry_id
    )
    assert hass.states.get("sensor.battery_testbat00000002_battery").state == "57"

    mock_read.return_value = replace(snapshot, batteries=())
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.battery_testbat00000001_battery") is None

    assert not device_registry.async_get_device_by_identifier(
        (DOMAIN, BATTERY_SERIAL_NUMBER), init_integration.entry_id
    )
    assert not device_registry.async_get_device_by_identifier(
        (DOMAIN, "TESTBAT00000002"), init_integration.entry_id
    )


async def test_missing_values_show_unknown(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_read: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a reported key without a valid value shows as unknown."""
    snapshot = build_snapshot()
    mock_read.return_value = replace(
        snapshot,
        properties={
            **snapshot.properties,
            "packState": None,
            "heatState": None,
            "acMode": None,
            "lampSwitch": None,
        },
    )
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    for entity_id in (
        "sensor.solarflow_2400_ac_battery_state",
        "binary_sensor.solarflow_2400_ac_battery_heating",
        "select.solarflow_2400_ac_ac_mode",
        "switch.solarflow_2400_ac_indicator_light",
    ):
        assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_battery_unavailable_until_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_read: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test sensors of a pack that is no longer reported are unavailable."""
    mock_read.return_value = replace(build_snapshot(), batteries=())
    with patch.object(dr.DeviceRegistry, "async_remove_device"):
        freezer.tick(timedelta(seconds=15))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.battery_testbat00000001_battery").state
        == STATE_UNAVAILABLE
    )
