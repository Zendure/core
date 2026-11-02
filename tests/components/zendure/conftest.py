"""Fixtures for the Zendure integration tests."""

from collections.abc import Generator
from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from zendure import Availability, BatterySnapshot, DeviceSnapshot
from zendure.ble import ProvisionResult

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.components.zendure.const import DOMAIN
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry, load_json_object_fixture
from tests.components.bluetooth import generate_advertisement_data, generate_ble_device

SERIAL_NUMBER = "TESTDEV00000001"
BATTERY_SERIAL_NUMBER = "TESTBAT00000001"
BLE_ADDRESS = "AA:BB:CC:DD:EE:FF"
BLE_NAME = "ZenTST_1"


def _manufacturer_data(serial_number: str) -> dict[int, bytes]:
    """Encode a serial number the way the device advertises it."""
    raw = serial_number.encode()
    return {int.from_bytes(raw[:2], "little"): raw[2:] + b"\x16"}


def bluetooth_discovery(
    manufacturer_data: dict[int, bytes] | None = None,
) -> BluetoothServiceInfoBleak:
    """Build the advertisement of a Zendure device waiting for Wi-Fi."""
    if manufacturer_data is None:
        manufacturer_data = _manufacturer_data(SERIAL_NUMBER)
    return BluetoothServiceInfoBleak(
        name=BLE_NAME,
        address=BLE_ADDRESS,
        rssi=-60,
        manufacturer_data=manufacturer_data,
        service_uuids=[],
        service_data={},
        source="local",
        device=generate_ble_device(address=BLE_ADDRESS, name=BLE_NAME),
        advertisement=generate_advertisement_data(
            local_name=BLE_NAME, manufacturer_data=manufacturer_data
        ),
        time=0,
        connectable=True,
        tx_power=-127,
    )


BLUETOOTH_DISCOVERY = bluetooth_discovery()


@pytest.fixture(autouse=True)
def mock_bluetooth(enable_bluetooth: None) -> None:
    """Auto mock bluetooth."""


def build_snapshot(fixture: str = "device_snapshot.json") -> DeviceSnapshot:
    """Build a device snapshot from a fixture of decoded values."""
    data = load_json_object_fixture(fixture, DOMAIN)
    return DeviceSnapshot(
        serial_number=data["serial_number"],
        model_key=data["model_key"],
        product_raw=data["product_raw"],
        availability=Availability.ONLINE,
        properties=data["properties"],
        batteries=tuple(
            BatterySnapshot(
                serial_number=battery["serial_number"],
                properties=battery["properties"],
                pack_type=battery["pack_type"],
                model_key=battery["model_key"],
            )
            for battery in data["batteries"]
        ),
        protocol_version=data["protocol_version"],
    )


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the default mocked config entry."""
    return MockConfigEntry(
        title="SolarFlow 2400 AC+",
        domain=DOMAIN,
        data={CONF_HOST: "192.168.1.50"},
        unique_id=SERIAL_NUMBER,
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Mock setting up a config entry."""
    with patch(
        "homeassistant.components.zendure.async_setup_entry", return_value=None
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_read() -> AsyncMock:
    """Return the mocked device read, to change what the device reports."""
    return AsyncMock(return_value=build_snapshot())


@pytest.fixture
def mock_read_faults() -> AsyncMock:
    """Return the mocked fault read; only its active faults are used."""
    return AsyncMock(return_value=replace(build_snapshot(), active_faults=()))


@pytest.fixture
def mock_zendure(
    mock_read: AsyncMock, mock_read_faults: AsyncMock
) -> Generator[MagicMock]:
    """Return a mocked Zendure client shared by setup and the config flow."""
    client = MagicMock()
    client.configure_mock(
        async_refresh=mock_read,
        async_refresh_faults=mock_read_faults,
        faults_supported=True,
    )
    client.async_set = AsyncMock(return_value=build_snapshot())
    client.close = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch(
            "homeassistant.components.zendure.create_local_client",
            return_value=client,
        ) as factory,
        patch(
            "homeassistant.components.zendure.config_flow.create_local_client",
            new=factory,
        ),
    ):
        yield client


@pytest.fixture
def mock_ble_client() -> Generator[MagicMock]:
    """Return the BLE client the config flow connects with."""
    client = MagicMock()
    client.disconnect = AsyncMock()
    with (
        patch(
            "homeassistant.components.zendure.config_flow.async_ble_device_from_address",
            return_value=BLUETOOTH_DISCOVERY.device,
        ),
        patch(
            "homeassistant.components.zendure.config_flow.establish_connection",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def mock_provision() -> Generator[AsyncMock]:
    """Return the mocked Wi-Fi provisioning call."""
    with patch(
        "homeassistant.components.zendure.config_flow.async_provision_wifi",
        return_value=ProvisionResult(SERIAL_NUMBER, "192.168.1.80"),
    ) as provision:
        yield provision


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_zendure: MagicMock,
    request: pytest.FixtureRequest,
) -> MockConfigEntry:
    """Set up the Zendure integration for testing."""
    mock_config_entry.add_to_hass(hass)

    context = nullcontext()
    if platform := getattr(request, "param", None):
        context = patch("homeassistant.components.zendure.PLATFORMS", [platform])

    with context:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    return mock_config_entry
