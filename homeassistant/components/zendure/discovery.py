"""Find a provisioned Zendure device on the local network over mDNS."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

from zendure import DeviceSnapshot
from zendure.protocols.local_http.discovery import parse_mdns_hostname
from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from .const import LOGGER

SERVICE_TYPE: Final = "_http._tcp.local."
RESOLVE_TIMEOUT_MS: Final = 3000
# Retry known names: a cached record may still carry the address from before
# the device joined the new network.
RETRY_INTERVAL: Final = 5.0

type Validate = Callable[[str], Awaitable[DeviceSnapshot | None]]


def _serial_number(service_name: str) -> str | None:
    """Return the serial number in a ``zendure-<model>-<sn>`` service name."""
    instance = service_name.removesuffix(f".{SERVICE_TYPE}")
    if parsed := parse_mdns_hostname(f"{instance}.local"):
        return parsed[1]
    return None


async def async_find_device(
    aiozc: AsyncZeroconf,
    serial_number: str,
    validate: Validate,
    timeout: float,
) -> tuple[str, DeviceSnapshot] | None:
    """Wait until the device with ``serial_number`` answers on the network.

    ``validate`` reads a candidate host and returns its snapshot, or ``None``
    to keep waiting. Returns ``None`` when ``timeout`` expires.
    """
    wanted = serial_number.upper()
    found: asyncio.Queue[str] = asyncio.Queue()
    known: list[str] = []

    def on_change(
        zeroconf: object,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        if (serial := _serial_number(name)) and serial.upper() == wanted:
            found.put_nowait(name)

    browser = AsyncServiceBrowser(aiozc.zeroconf, SERVICE_TYPE, handlers=[on_change])
    try:
        async with asyncio.timeout(timeout):
            while True:
                try:
                    name = await asyncio.wait_for(found.get(), RETRY_INTERVAL)
                except TimeoutError:
                    pass
                else:
                    if name not in known:
                        LOGGER.debug("mDNS found %s", name)
                        known.append(name)
                for name in known:
                    if result := await _async_try(aiozc, name, validate):
                        return result
    except TimeoutError:
        LOGGER.debug("mDNS did not find %s within %g s", serial_number, timeout)
        return None
    finally:
        await browser.async_cancel()


async def _async_try(
    aiozc: AsyncZeroconf, name: str, validate: Validate
) -> tuple[str, DeviceSnapshot] | None:
    """Resolve ``name`` and validate each of its IPv4 addresses."""
    info = AsyncServiceInfo(SERVICE_TYPE, name)
    if not await info.async_request(aiozc.zeroconf, RESOLVE_TIMEOUT_MS):
        LOGGER.debug("mDNS could not resolve %s", name)
        return None
    for host in info.parsed_addresses(IPVersion.V4Only):
        LOGGER.debug("mDNS %s resolved to %s, checking it", name, host)
        if snapshot := await validate(host):
            return host, snapshot
    return None
