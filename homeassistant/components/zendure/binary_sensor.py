"""Binary sensor platform for Zendure devices."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZendureConfigEntry
from .entity import ZendureEntity, ZendureFaultEntity

PARALLEL_UPDATES = 0

PROBLEM = BinarySensorEntityDescription(
    key="problem",
    device_class=BinarySensorDeviceClass.PROBLEM,
)

BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="heatState",
        translation_key="battery_heating",
        device_class=BinarySensorDeviceClass.HEAT,
    ),
    BinarySensorEntityDescription(
        key="pass",
        translation_key="bypass",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="reverseState",
        translation_key="reverse_flow",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="socStatus",
        translation_key="soc_calibration",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZendureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Zendure binary sensors based on a config entry."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        ZendureBinarySensorEntity(coordinator, description)
        for description in BINARY_SENSORS
        if description.key in coordinator.data.properties
    ]
    # Unknown support (first fault read failed) still gets the entity; it
    # only stays out when the device said it has no fault codes.
    if coordinator.client.faults_supported is not False:
        entities.append(ZendureProblemBinarySensorEntity(coordinator, PROBLEM))
    async_add_entities(entities)


class ZendureBinarySensorEntity(ZendureEntity, BinarySensorEntity):
    """A binary sensor of the Zendure device."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        if (value := self.raw_value) is None:
            return None
        return bool(value)


class ZendureProblemBinarySensorEntity(ZendureFaultEntity, BinarySensorEntity):
    """On while the device reports a fault the user should see."""

    @property
    @override
    def is_on(self) -> bool:
        """Return if the device reports a visible fault."""
        return bool(self.visible_faults)
