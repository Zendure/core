"""Select platform for Zendure devices."""

from dataclasses import dataclass
from typing import override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZendureConfigEntry, ZendureDataUpdateCoordinator
from .entity import ZendureEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ZendureSelectEntityDescription(SelectEntityDescription):
    """Describes a Zendure select entity."""

    raw_options: dict[int, str]


SELECTS: tuple[ZendureSelectEntityDescription, ...] = (
    ZendureSelectEntityDescription(
        key="acMode",
        translation_key="ac_mode",
        raw_options={1: "input", 2: "output"},
    ),
    ZendureSelectEntityDescription(
        key="gridOffMode",
        translation_key="off_grid_mode",
        raw_options={0: "normal", 1: "eco", 2: "off"},
        entity_category=EntityCategory.CONFIG,
    ),
    ZendureSelectEntityDescription(
        key="gridReverse",
        translation_key="grid_feed_in",
        raw_options={0: "disabled", 1: "allow", 2: "forbidden"},
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZendureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Zendure selects based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        ZendureSelectEntity(coordinator, description)
        for description in SELECTS
        if description.key in coordinator.data.properties
    )


class ZendureSelectEntity(ZendureEntity, SelectEntity):
    """A writable mode setting of the Zendure device."""

    entity_description: ZendureSelectEntityDescription

    def __init__(
        self,
        coordinator: ZendureDataUpdateCoordinator,
        description: ZendureSelectEntityDescription,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, description)
        self._attr_options = list(description.raw_options.values())
        self._raw_by_option = {
            option: raw for raw, option in description.raw_options.items()
        }

    @property
    @override
    def current_option(self) -> str | None:
        """Return the current mode, or unknown for an unrecognized code."""
        value = self.raw_value
        if not isinstance(value, int):
            return None
        return self.entity_description.raw_options.get(value)

    @override
    async def async_select_option(self, option: str) -> None:
        """Change the mode."""
        await self.coordinator.async_set(
            self.entity_description.key, self._raw_by_option[option]
        )
