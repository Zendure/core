"""Base entities for the Zendure integration."""

from typing import override

from zendure import BatterySnapshot, PropertyValue
from zendure.catalog import FaultDescription, lookup_device, lookup_fault

from homeassistant.const import CONF_HOST
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ZendureDataUpdateCoordinator


def device_info(coordinator: ZendureDataUpdateCoordinator) -> DeviceInfo:
    """Return the device info of the Zendure device itself."""
    snapshot = coordinator.data
    # The library only produces snapshots for registered models.
    model = lookup_device(snapshot.product_raw).display_name
    return DeviceInfo(
        configuration_url=f"http://{coordinator.config_entry.data[CONF_HOST]}",
        identifiers={(DOMAIN, snapshot.serial_number)},
        manufacturer=MANUFACTURER,
        model=model,
        model_id=snapshot.product_raw,
        name=model,
        serial_number=snapshot.serial_number,
    )


class ZendureEntity(CoordinatorEntity[ZendureDataUpdateCoordinator]):
    """An entity of the Zendure device itself."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZendureDataUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.data.serial_number}_{description.key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def raw_value(self) -> PropertyValue:
        """Return the reported value for this entity's key."""
        return self.coordinator.data.properties.get(self.entity_description.key)


class ZendureFaultEntity(ZendureEntity):
    """An entity derived from the device's active fault codes."""

    @property
    def visible_faults(self) -> list[FaultDescription]:
        """Return the active faults the Zendure app would show to the user."""
        snapshot = self.coordinator.data
        return [
            fault
            for code in snapshot.active_faults or ()
            if (fault := lookup_fault(snapshot.model_key, code)).visible
        ]

    @property
    @override
    def available(self) -> bool:
        """Return if the fault codes could be read."""
        return super().available and self.coordinator.data.active_faults is not None


class ZendureBatteryEntity(CoordinatorEntity[ZendureDataUpdateCoordinator]):
    """An entity of one battery pack attached to a Zendure device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZendureDataUpdateCoordinator,
        description: EntityDescription,
        battery_serial_number: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._battery_serial_number = battery_serial_number
        self._attr_unique_id = f"{battery_serial_number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, battery_serial_number)},
            manufacturer=MANUFACTURER,
            name=f"Battery {battery_serial_number}",
            serial_number=battery_serial_number,
            via_device_id=dr.async_get_device_id_by_identifier(
                coordinator.hass,
                (DOMAIN, coordinator.data.serial_number),
                config_entry_id=coordinator.config_entry.entry_id,
            ),
        )

    @property
    def battery(self) -> BatterySnapshot | None:
        """Return the current snapshot of this battery pack."""
        for battery in self.coordinator.data.batteries:
            if battery.serial_number == self._battery_serial_number:
                return battery
        return None

    @property
    def raw_value(self) -> PropertyValue:
        """Return the reported value for this entity's key."""
        if (battery := self.battery) is None:
            return None
        return battery.properties.get(self.entity_description.key)

    @property
    @override
    def available(self) -> bool:
        """Return if the battery pack is still reported by the device."""
        return super().available and self.battery is not None
