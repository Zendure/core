"""Diagnostics support for Zendure devices."""

from typing import Any

from zendure.catalog import lookup_fault

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import ZendureConfigEntry

TO_REDACT = {CONF_HOST, "serial_number", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZendureConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    snapshot = coordinator.data
    # Hidden codes are listed too: support needs every code the device sent.
    faults = (
        None
        if snapshot.active_faults is None
        else [
            {
                "code": fault.code,
                "name": fault.name,
                "module": fault.module,
                "level": fault.level,
                "visible": fault.visible,
                "known": fault.known,
                "since": snapshot.fault_since.get(fault.code),
            }
            for fault in (
                lookup_fault(snapshot.model_key, code)
                for code in snapshot.active_faults
            )
        ]
    )
    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "device": {
                "serial_number": snapshot.serial_number,
                "model_key": snapshot.model_key,
                "product": snapshot.product_raw,
                "availability": snapshot.availability,
                "protocol_version": snapshot.protocol_version,
                "faults_supported": coordinator.client.faults_supported,
                "active_faults": faults,
                "properties": dict(snapshot.properties),
                "batteries": [
                    {
                        "serial_number": battery.serial_number,
                        "pack_type": battery.pack_type,
                        "model_key": battery.model_key,
                        "properties": dict(battery.properties),
                    }
                    for battery in snapshot.batteries
                ],
            },
        },
        TO_REDACT,
    )
