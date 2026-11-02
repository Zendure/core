"""Switch platform for Zendure devices."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZendureConfigEntry
from .entity import ZendureEntity

PARALLEL_UPDATES = 1

SWITCHES: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="lampSwitch",
        translation_key="indicator_light",
        entity_category=EntityCategory.CONFIG,
    ),
    # On means settings are kept in RAM only and revert after a device restart.
    SwitchEntityDescription(
        key="smartMode",
        translation_key="temporary_settings",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZendureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Zendure switches based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        ZendureSwitchEntity(coordinator, description)
        for description in SWITCHES
        if description.key in coordinator.data.properties
    )


class ZendureSwitchEntity(ZendureEntity, SwitchEntity):
    """A writable on/off setting of the Zendure device."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state of the switch."""
        if (value := self.raw_value) is None:
            return None
        return bool(value)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.coordinator.async_set(self.entity_description.key, 1)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.coordinator.async_set(self.entity_description.key, 0)
