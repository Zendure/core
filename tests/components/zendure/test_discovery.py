"""Tests for finding a provisioned Zendure device over mDNS."""

import asyncio
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from zendure import DeviceSnapshot
from zeroconf import ServiceStateChange

from homeassistant.components.zendure.discovery import async_find_device

from .conftest import SERIAL_NUMBER, build_snapshot

NAME = f"zendure-solarFlow2400AC+-{SERIAL_NUMBER}._http._tcp.local."
SNAPSHOT = build_snapshot()


class FakeBrowser:
    """Capture the handler the browser would call on service changes."""

    instances: list[FakeBrowser] = []

    def __init__(self, zc: Any, service_type: str, handlers: list[Callable]) -> None:
        """Record the handler and register the instance."""
        self.handler = handlers[0]
        self.async_cancel = AsyncMock()
        FakeBrowser.instances.append(self)

    def announce(
        self, name: str, state: ServiceStateChange = ServiceStateChange.Added
    ) -> None:
        """Simulate an mDNS service change."""
        self.handler(
            zeroconf=None,
            service_type="_http._tcp.local.",
            name=name,
            state_change=state,
        )


@pytest.fixture
def addresses() -> Generator[dict[str, list[str]]]:
    """Map service names to the IPv4 addresses they resolve to."""
    resolved: dict[str, list[str]] = {}

    class FakeServiceInfo:
        def __init__(self, service_type: str, name: str) -> None:
            self.name = name

        async def async_request(self, zc: Any, timeout: int) -> bool:
            return self.name in resolved

        def parsed_addresses(self, version: Any) -> list[str]:
            return resolved[self.name]

    FakeBrowser.instances = []
    with (
        patch(
            "homeassistant.components.zendure.discovery.AsyncServiceBrowser",
            FakeBrowser,
        ),
        patch(
            "homeassistant.components.zendure.discovery.AsyncServiceInfo",
            FakeServiceInfo,
        ),
        patch("homeassistant.components.zendure.discovery.RETRY_INTERVAL", 0.01),
    ):
        yield resolved


async def _start(
    validate: AsyncMock, timeout: float = 1
) -> tuple[asyncio.Task[tuple[str, DeviceSnapshot] | None], FakeBrowser]:
    task = asyncio.create_task(
        async_find_device(MagicMock(), SERIAL_NUMBER, validate, timeout)
    )
    await asyncio.sleep(0)
    return task, FakeBrowser.instances[-1]


async def test_find_device(addresses: dict[str, list[str]]) -> None:
    """Test the device is found once it announces itself, in any letter case."""
    addresses[NAME.lower()] = ["192.168.1.90"]
    validate = AsyncMock(return_value=SNAPSHOT)
    task, browser = await _start(validate)

    browser.announce("zendure-other-OTHERDEV0000001._http._tcp.local.")
    browser.announce("shelly1-ABCDEF._http._tcp.local.")
    browser.announce(NAME, ServiceStateChange.Removed)
    browser.announce(NAME.lower())

    assert await task == ("192.168.1.90", SNAPSHOT)
    validate.assert_awaited_once_with("192.168.1.90")
    browser.async_cancel.assert_awaited_once()


async def test_find_device_retries_stale_address(
    addresses: dict[str, list[str]],
) -> None:
    """Test a cached old address is retried until the device answers."""
    addresses[NAME] = ["192.168.1.10", "192.168.1.90"]
    validate = AsyncMock(side_effect=[None, None, None, SNAPSHOT])
    task, browser = await _start(validate)

    browser.announce(NAME)
    browser.announce(NAME, ServiceStateChange.Updated)

    assert await task == ("192.168.1.90", SNAPSHOT)
    assert validate.await_count == 4


async def test_find_device_unresolvable(addresses: dict[str, list[str]]) -> None:
    """Test a name that never resolves times out."""
    validate = AsyncMock()
    task, browser = await _start(validate, timeout=0.05)

    browser.announce(NAME)

    assert await task is None
    validate.assert_not_awaited()
    browser.async_cancel.assert_awaited_once()


async def test_find_device_timeout(addresses: dict[str, list[str]]) -> None:
    """Test nothing is returned when the device never shows up."""
    validate = AsyncMock()
    task, browser = await _start(validate, timeout=0.05)

    assert await task is None
    validate.assert_not_awaited()
    browser.async_cancel.assert_awaited_once()
