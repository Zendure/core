"""Tests for the Zendure sensor platform."""

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.zendure import sensor
from homeassistant.components.zendure.sensor import (
    CURRENT_FAULT_TRANSLATION_KEYS,
    _current_fault_description,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import build_snapshot

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform


@pytest.mark.parametrize("init_integration", [Platform.SENSOR], indirect=True)
@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the sensor entities."""
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.parametrize("init_integration", [Platform.SENSOR], indirect=True)
@pytest.mark.usefixtures("init_integration")
async def test_unknown_values(
    hass: HomeAssistant,
    mock_read: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test an invalid value and an unrecognized state code show as unknown."""
    snapshot = build_snapshot()
    mock_read.return_value = replace(
        snapshot,
        properties={**snapshot.properties, "remainOutTime": None, "packState": 9},
    )
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.solarflow_2400_ac_remaining_discharge_time").state
        == STATE_UNKNOWN
    )
    assert hass.states.get("sensor.solarflow_2400_ac_battery_state").state == (
        STATE_UNKNOWN
    )


@pytest.mark.parametrize("init_integration", [Platform.SENSOR], indirect=True)
@pytest.mark.usefixtures("init_integration")
async def test_fault_count(
    hass: HomeAssistant,
    mock_read_faults: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the fault count leaves out codes the Zendure app does not show."""
    entity_id = "sensor.solarflow_2400_ac_active_faults"
    assert hass.states.get(entity_id).state == "0"

    # 6 and 999 are shown; 34 is a hidden code.
    mock_read_faults.return_value = replace(
        build_snapshot(), active_faults=(6, 34, 999)
    )
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "2"


@pytest.mark.parametrize("init_integration", [Platform.SENSOR], indirect=True)
@pytest.mark.parametrize(
    ("active_faults", "state"),
    [
        ((), "none"),
        ((6,), "6"),
        # A warning (52) does not hide a later fault (6).
        ((52, 6), "6"),
        ((52,), "52"),
        # Hidden codes are not shown.
        ((34,), "none"),
        # A visible code missing from the table.
        ((999,), "other"),
        ((999, 6), "6"),
        (None, STATE_UNAVAILABLE),
    ],
)
@pytest.mark.usefixtures("init_integration")
async def test_current_fault(
    hass: HomeAssistant,
    mock_read_faults: AsyncMock,
    freezer: FrozenDateTimeFactory,
    active_faults: tuple[int, ...] | None,
    state: str,
) -> None:
    """Test the current fault shows the most severe visible fault code."""
    mock_read_faults.return_value = replace(
        build_snapshot(), active_faults=active_faults
    )
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.solarflow_2400_ac_current_fault").state == state


@pytest.mark.usefixtures("mock_zendure")
async def test_current_fault_per_model(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read: AsyncMock,
    mock_read_faults: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test each model names its own fault codes."""
    snapshot = replace(build_snapshot(), model_key="solarflow_5000_max_pro")
    mock_read.return_value = snapshot
    mock_read_faults.return_value = replace(snapshot, active_faults=(6,))
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = entity_registry.async_get_entity_id(
        "sensor", "zendure", "TESTDEV00000001_current_fault"
    )
    assert entity_id
    assert entity_registry.async_get(entity_id).translation_key == (
        "current_fault_5000_max_pro"
    )
    assert hass.states.get(entity_id).state == "6"


@pytest.mark.usefixtures("mock_zendure")
async def test_no_current_fault_for_unnamed_model(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test a model without named fault codes only gets the fault count."""
    mock_read.return_value = replace(build_snapshot(), model_key="unknown_model")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not entity_registry.async_get_entity_id(
        "sensor", "zendure", "TESTDEV00000001_current_fault"
    )
    assert entity_registry.async_get_entity_id(
        "sensor", "zendure", "TESTDEV00000001_fault_count"
    )


@pytest.mark.parametrize("model_key", list(CURRENT_FAULT_TRANSLATION_KEYS))
def test_current_fault_states_are_translated(model_key: str) -> None:
    """Test every state of each current-fault sensor has a translation."""
    strings = json.loads(
        (Path(sensor.__file__).parent / "strings.json").read_text(encoding="utf-8")
    )
    description = _current_fault_description(model_key)
    assert description is not None
    translated = strings["entity"]["sensor"][description.translation_key]["state"]
    assert list(translated) == description.options


@pytest.mark.usefixtures("mock_zendure")
async def test_missing_key_creates_no_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test a property the device does not report creates no entity."""
    snapshot = build_snapshot()
    properties = dict(snapshot.properties)
    del properties["solarPower4"]
    mock_read.return_value = replace(snapshot, properties=properties)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not entity_registry.async_get_entity_id(
        "sensor", "zendure", "TESTDEV00000001_solarPower4"
    )
    assert entity_registry.async_get_entity_id(
        "sensor", "zendure", "TESTDEV00000001_solarPower3"
    )
