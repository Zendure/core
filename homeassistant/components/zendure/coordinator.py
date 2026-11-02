"""Data update coordinator for Zendure devices."""

from dataclasses import replace
from typing import override

from zendure import (
    DeviceSnapshot,
    PropertyValue,
    UnsupportedPropertyError,
    ValidationError,
    WriteNotConfirmedError,
    WriteRejectedError,
    ZendureClient,
    ZendureConnectionError,
    ZendureError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER, SCAN_INTERVAL

type ZendureConfigEntry = ConfigEntry[ZendureDataUpdateCoordinator]


class ZendureDataUpdateCoordinator(DataUpdateCoordinator[DeviceSnapshot]):
    """Poll one Zendure device over the local network."""

    config_entry: ZendureConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ZendureConfigEntry,
        client: ZendureClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.unique_id}",
            update_interval=SCAN_INTERVAL,
        )
        self.client = client

    @override
    async def _async_update_data(self) -> DeviceSnapshot:
        """Fetch the latest snapshot from the device."""
        try:
            snapshot = await self.client.async_refresh()
        except ZendureConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
        except ZendureError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unknown_error",
                translation_placeholders={"error": str(err)},
            ) from err
        self._async_remove_stale_batteries(snapshot)
        if (faults := await self._async_read_faults()) is None:
            return replace(snapshot, active_faults=None, fault_since={})
        return replace(
            snapshot,
            active_faults=faults.active_faults,
            fault_since=faults.fault_since,
        )

    async def _async_read_faults(self) -> DeviceSnapshot | None:
        """Return the snapshot with fault codes, or None when they cannot be read.

        Fault codes come from a separate endpoint; failing to read them must
        not make the rest of the device unavailable. The library logs outages.
        """
        if self.client.faults_supported is False:
            return None
        try:
            return await self.client.async_refresh_faults()
        except ZendureError:
            return None

    def _async_remove_stale_batteries(self, snapshot: DeviceSnapshot) -> None:
        """Remove devices of battery packs the device no longer reports."""
        if self.data is None:
            return
        current = {battery.serial_number for battery in snapshot.batteries}
        gone = {
            battery.serial_number
            for battery in self.data.batteries
            if battery.serial_number not in current
        }
        if not gone:
            return
        device_registry = dr.async_get(self.hass)
        for serial_number in gone:
            if device := device_registry.async_get_device_by_identifier(
                (DOMAIN, serial_number), self.config_entry.entry_id
            ):
                device_registry.async_remove_device(device.id)

    async def async_set(self, key: str, value: PropertyValue) -> None:
        """Write a property and publish the snapshot the device confirmed."""
        try:
            snapshot = await self.client.async_set(key, value)
        except (ValidationError, UnsupportedPropertyError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"key": key, "error": str(err)},
            ) from err
        except WriteRejectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_rejected",
                translation_placeholders={"key": key, "error": str(err)},
            ) from err
        except WriteNotConfirmedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_not_confirmed",
                translation_placeholders={"key": key},
            ) from err
        except ZendureConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
        except ZendureError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_error",
                translation_placeholders={"error": str(err)},
            ) from err
        self.async_set_updated_data(snapshot)
