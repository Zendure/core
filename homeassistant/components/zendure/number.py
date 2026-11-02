"""Number platform for Zendure devices."""

from typing import override

from zendure import ControlDescription
from zendure.catalog import control

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZendureConfigEntry, ZendureDataUpdateCoordinator
from .entity import ZendureEntity

PARALLEL_UPDATES = 1

NUMBERS: tuple[NumberEntityDescription, ...] = (
    NumberEntityDescription(
        key="outputLimit",
        translation_key="output_limit",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="inputLimit",
        translation_key="input_limit",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="socSet",
        translation_key="charge_limit",
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZendureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Zendure numbers based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        ZendureNumberEntity(coordinator, description, limits)
        for description in NUMBERS
        if (limits := control(description.key)) is not None
        and description.key in coordinator.data.properties
    )


class ZendureNumberEntity(ZendureEntity, NumberEntity):
    """A writable numeric setting of the Zendure device.

    Bounds come from the library's control table; a power limit's upper bound
    is whatever the device currently reports for its source key.
    """

    def __init__(
        self,
        coordinator: ZendureDataUpdateCoordinator,
        description: NumberEntityDescription,
        limits: ControlDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, description)
        self._limits = limits
        if limits.native_min is not None:
            self._attr_native_min_value = limits.native_min
        if limits.step is not None:
            self._attr_native_step = limits.step

    @property
    def _upper_bound(self) -> float | None:
        """Return the current upper bound, if known."""
        if (source := self._limits.max_source_key) is not None:
            bound = self.coordinator.data.properties.get(source)
            return float(bound) if isinstance(bound, int | float) else None
        return self._limits.native_max

    @property
    @override
    def available(self) -> bool:
        """Return if the setting can be shown and changed."""
        return super().available and self._upper_bound is not None

    @property
    @override
    def native_max_value(self) -> float:
        """Return the maximum the device currently accepts."""
        if (bound := self._upper_bound) is None:
            return super().native_max_value
        return bound

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current setting."""
        value = self.raw_value
        return float(value) if isinstance(value, int | float) else None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        await self.coordinator.async_set(
            self.entity_description.key, int(value) if value.is_integer() else value
        )
