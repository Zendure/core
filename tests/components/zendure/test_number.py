"""Tests for the Zendure number platform."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion
from zendure import (
    ValidationError,
    WriteNotConfirmedError,
    WriteRejectedError,
    ZendureConnectionError,
    ZendureError,
)

from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.zendure.const import DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import build_snapshot

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform

pytestmark = pytest.mark.parametrize(
    "init_integration", [Platform.NUMBER], indirect=True
)

OUTPUT_LIMIT = "number.solarflow_2400_ac_output_limit"


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "init_integration")
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the number entities."""
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("entity_id", "value", "key", "expected"),
    [
        (OUTPUT_LIMIT, 300, "outputLimit", 300),
        ("number.solarflow_2400_ac_input_limit", 400, "inputLimit", 400),
        ("number.solarflow_2400_ac_charge_limit", 90, "socSet", 90),
    ],
)
async def test_set_value(
    hass: HomeAssistant,
    mock_zendure: MagicMock,
    entity_id: str,
    value: float,
    key: str,
    expected: int,
) -> None:
    """Test setting a number writes the property through the library."""
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )

    mock_zendure.async_set.assert_awaited_once_with(key, expected)


@pytest.mark.usefixtures("init_integration")
async def test_dynamic_maximum(
    hass: HomeAssistant,
    mock_read: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a power limit follows the maximum the device reports."""
    assert hass.states.get(OUTPUT_LIMIT).attributes[ATTR_MAX] == 800

    snapshot = build_snapshot()
    mock_read.return_value = replace(
        snapshot, properties={**snapshot.properties, "inverseMaxPower": 600}
    )
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(OUTPUT_LIMIT).attributes[ATTR_MAX] == 600

    mock_read.return_value = replace(
        snapshot, properties={**snapshot.properties, "inverseMaxPower": None}
    )
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(OUTPUT_LIMIT).state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("side_effect", "expected", "translation_key"),
    [
        (ValidationError("out of range"), ServiceValidationError, "invalid_value"),
        (
            WriteRejectedError("rejected", code=500),
            HomeAssistantError,
            "write_rejected",
        ),
        (WriteNotConfirmedError("no"), HomeAssistantError, "write_not_confirmed"),
        (ZendureConnectionError("down"), HomeAssistantError, "communication_error"),
        (ZendureError("odd"), HomeAssistantError, "unknown_error"),
    ],
)
async def test_set_value_errors(
    hass: HomeAssistant,
    mock_zendure: MagicMock,
    side_effect: Exception,
    expected: type[Exception],
    translation_key: str,
) -> None:
    """Test a failed write raises a translated error."""
    mock_zendure.async_set.side_effect = side_effect

    with pytest.raises(expected) as excinfo:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: OUTPUT_LIMIT, ATTR_VALUE: 300},
            blocking=True,
        )

    assert excinfo.value.translation_domain == DOMAIN
    assert excinfo.value.translation_key == translation_key
