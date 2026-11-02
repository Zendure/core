"""Integration for Zendure energy storage devices."""

from zendure import create_local_client

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import ZendureConfigEntry, ZendureDataUpdateCoordinator
from .entity import device_info

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ZendureConfigEntry) -> None:
    """Set up Zendure from a config entry."""
    client = create_local_client(
        entry.data[CONF_HOST],
        async_get_clientsession(hass),
        expected_serial_number=entry.unique_id,
    )
    entry.async_on_unload(client.close)

    coordinator = ZendureDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Battery packs link to the device, so it must be registered first.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **device_info(coordinator)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: ZendureConfigEntry) -> None:
    """Unload a Zendure config entry."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
