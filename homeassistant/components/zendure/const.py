"""Constants for the Zendure integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "zendure"
LOGGER = logging.getLogger(__package__)

MANUFACTURER: Final = "Zendure"

CONF_SSID: Final = "ssid"

# Seconds to wait for a provisioned device to appear over mDNS.
MDNS_TIMEOUT: Final = 60.0

# The device only answers over the LAN and a report is a single small GET.
SCAN_INTERVAL: Final = timedelta(seconds=15)
