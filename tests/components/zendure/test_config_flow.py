"""Configuration flow tests for the Zendure integration."""

from collections.abc import Generator
from dataclasses import replace
from ipaddress import ip_address
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
import pytest
from zendure import (
    MalformedResponseError,
    ProvisioningFailedError,
    ProvisioningTimeoutError,
    UnsupportedDeviceError,
    ValidationError,
    ZendureConnectionError,
    ZendureProtocolError,
)
from zendure.ble import ProvisionResult

from homeassistant.components.zendure.const import CONF_SSID, DOMAIN
from homeassistant.config_entries import (
    SOURCE_BLUETOOTH,
    SOURCE_USER,
    SOURCE_ZEROCONF,
    ConfigFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import (
    BLE_NAME,
    BLUETOOTH_DISCOVERY,
    SERIAL_NUMBER,
    bluetooth_discovery,
    build_snapshot,
)

from tests.common import MockConfigEntry, get_schema_suggested_value

WIFI_INPUT = {CONF_SSID: "MyWiFi", CONF_PASSWORD: "secret123"}

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

ZEROCONF_DISCOVERY = ZeroconfServiceInfo(
    ip_address=ip_address("192.168.1.60"),
    ip_addresses=[ip_address("192.168.1.60")],
    port=80,
    hostname=f"zendure-solarFlow2400AC+-{SERIAL_NUMBER}.local.",
    name=f"zendure-solarFlow2400AC+-{SERIAL_NUMBER}._http._tcp.local.",
    properties={},
    type="_http._tcp.local.",
)


@pytest.mark.usefixtures("mock_zendure")
async def test_user_flow(hass: HomeAssistant) -> None:
    """Test the full happy path user flow from start to finish."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.50"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SolarFlow 2400 AC+"
    assert result["data"] == {CONF_HOST: "192.168.1.50"}
    assert result["result"].unique_id == SERIAL_NUMBER


@pytest.mark.usefixtures("mock_zendure")
@pytest.mark.parametrize(
    ("side_effect", "field", "error"),
    [
        (ZendureConnectionError, "base", "cannot_connect"),
        (UnsupportedDeviceError("someModel"), "base", "unsupported_device"),
        (ValidationError, CONF_HOST, "invalid_host"),
        (Exception, "base", "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    mock_read: AsyncMock,
    side_effect: Exception,
    field: str,
    error: str,
) -> None:
    """Test we show user form on an error and recover from it."""
    mock_read.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_HOST: "192.168.1.50"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {field: error}

    mock_read.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.50"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_zendure")
async def test_unsupported_product_is_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, mock_read: AsyncMock
) -> None:
    """Test the product string the device reports is logged when unsupported."""
    mock_read.side_effect = UnsupportedDeviceError("solarFlowNewModel")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with caplog.at_level(logging.DEBUG, logger="homeassistant.components.zendure"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_HOST: "192.168.1.50"}
        )

    assert result["errors"] == {"base": "unsupported_device"}
    assert (
        "Device at 192.168.1.50 reports unsupported product 'solarFlowNewModel'"
        in caplog.text
    )

    mock_read.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.50"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL_NUMBER


@pytest.mark.usefixtures("mock_zendure")
async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test configuring the same device twice updates its address."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_HOST: "192.168.1.99"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.99"


@pytest.mark.usefixtures("mock_zendure")
async def test_zeroconf_flow(hass: HomeAssistant) -> None:
    """Test the zeroconf happy flow from start to finish."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {
        "name": "SolarFlow 2400 AC+",
        "host": "192.168.1.60",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SolarFlow 2400 AC+"
    assert result["data"] == {CONF_HOST: "192.168.1.60"}
    assert result["result"].unique_id == SERIAL_NUMBER


@pytest.mark.usefixtures("mock_zendure")
async def test_zeroconf_already_configured_updates_host(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a rediscovered device gets its new address."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.60"


@pytest.mark.usefixtures("mock_zendure")
async def test_zeroconf_not_zendure(hass: HomeAssistant) -> None:
    """Test discovery of a host name not following the Zendure pattern."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=replace(ZEROCONF_DISCOVERY, hostname="something-else.local."),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_zendure_device"


@pytest.mark.usefixtures("mock_zendure")
async def test_zeroconf_unsupported_model_skips_read(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, mock_read: AsyncMock
) -> None:
    """Test another Zendure model is rejected from its name, without a read."""
    with caplog.at_level(logging.DEBUG, logger="homeassistant.components.zendure"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_ZEROCONF},
            data=replace(
                ZEROCONF_DISCOVERY,
                hostname=f"zendure-solarFlow3600Max-{SERIAL_NUMBER}.local.",
            ),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unsupported_device"
    mock_read.assert_not_awaited()
    assert "unsupported product 'solarFlow3600Max'" in caplog.text


@pytest.mark.usefixtures("mock_zendure")
@pytest.mark.parametrize(
    ("side_effect", "reason"),
    [
        (ZendureConnectionError, "cannot_connect"),
        (UnsupportedDeviceError("someModel"), "unsupported_device"),
        (ValidationError, "cannot_connect"),
    ],
)
async def test_zeroconf_errors(
    hass: HomeAssistant,
    mock_read: AsyncMock,
    side_effect: Exception,
    reason: str,
) -> None:
    """Test discovery aborts when the device cannot be read."""
    mock_read.side_effect = side_effect

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.usefixtures("mock_zendure")
async def test_zeroconf_different_device(
    hass: HomeAssistant, mock_read: AsyncMock
) -> None:
    """Test discovery aborts when another device answers on the address."""
    mock_read.return_value = replace(build_snapshot(), serial_number="OTHERDEV0000001")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "different_device"


@pytest.mark.usefixtures("mock_zendure")
async def test_reconfigure_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test changing the address of a configured device."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.70"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.70"


@pytest.mark.usefixtures("mock_zendure")
async def test_reconfigure_flow_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read: AsyncMock,
) -> None:
    """Test reconfigure shows an error and recovers from it."""
    mock_config_entry.add_to_hass(hass)
    mock_read.side_effect = ZendureConnectionError

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.70"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_read.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.70"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


@pytest.mark.usefixtures("mock_zendure")
async def test_reconfigure_flow_different_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read: AsyncMock,
) -> None:
    """Test reconfigure refuses to switch the entry to another device."""
    mock_config_entry.add_to_hass(hass)
    mock_read.return_value = replace(build_snapshot(), serial_number="OTHERDEV0000001")

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.70"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "different_device"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.50"


async def _start_bluetooth_flow(hass: HomeAssistant) -> ConfigFlowResult:
    """Start a Bluetooth discovery flow and return the Wi-Fi form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=BLUETOOTH_DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "wifi"
    return result


async def _submit_wifi(
    hass: HomeAssistant, result: ConfigFlowResult, user_input: dict[str, str]
) -> ConfigFlowResult:
    """Submit the Wi-Fi form and return the result once all progress ends."""
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "provision"
    assert result["progress_action"] == "provisioning"
    while result["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


@pytest.mark.usefixtures("mock_zendure")
async def test_bluetooth_flow(
    hass: HomeAssistant, mock_ble_client: MagicMock, mock_provision: AsyncMock
) -> None:
    """Test provisioning a new device over Bluetooth from start to finish."""
    result = await _start_bluetooth_flow(hass)
    assert result["description_placeholders"] == {"name": BLE_NAME}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=WIFI_INPUT
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "provision"
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "connect"
    assert result["progress_action"] == "connecting"
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SolarFlow 2400 AC+"
    assert result["data"] == {CONF_HOST: "192.168.1.80"}
    assert result["result"].unique_id == SERIAL_NUMBER
    mock_provision.assert_awaited_once_with(mock_ble_client, "MyWiFi", "secret123")
    mock_ble_client.disconnect.assert_awaited_once()


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client")
async def test_bluetooth_reply_device_id_is_not_serial(
    hass: HomeAssistant, mock_provision: AsyncMock
) -> None:
    """Test a reply deviceId that is not the serial number does not block setup."""
    mock_provision.return_value = ProvisionResult("CLOUDID00000001", "192.168.1.80")
    result = await _start_bluetooth_flow(hass)

    result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL_NUMBER


def _fake_find(hosts: list[str]) -> AsyncMock:
    """Return an mDNS lookup that offers ``hosts`` to the flow in order."""

    async def find(
        aiozc: Any, serial_number: str, validate: Any, timeout: float
    ) -> tuple[str, Any] | None:
        assert serial_number == SERIAL_NUMBER
        for host in hosts:
            if snapshot := await validate(host):
                return host, snapshot
        return None

    return AsyncMock(side_effect=find)


@pytest.fixture
def mock_find() -> Generator[None]:
    """Use a fake zeroconf instance for the mDNS lookup."""
    with patch(
        "homeassistant.components.zendure.config_flow.zeroconf.async_get_async_instance",
        return_value=MagicMock(),
    ):
        yield


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client", "mock_find")
async def test_bluetooth_finds_device_over_mdns(
    hass: HomeAssistant, mock_provision: AsyncMock, mock_read: AsyncMock
) -> None:
    """Test a reply without an address falls back to mDNS discovery."""
    mock_provision.return_value = ProvisionResult(SERIAL_NUMBER, None)
    mock_read.side_effect = [
        ZendureConnectionError,
        replace(build_snapshot(), serial_number="OTHERDEV0000001"),
        build_snapshot(),
    ]
    find = _fake_find(["192.168.1.10", "192.168.1.11", "192.168.1.90"])
    result = await _start_bluetooth_flow(hass)

    with patch("homeassistant.components.zendure.config_flow.async_find_device", find):
        result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.90"}
    assert result["result"].unique_id == SERIAL_NUMBER
    find.assert_awaited_once()


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client", "mock_find")
@pytest.mark.parametrize(
    ("hosts", "side_effect", "reason"),
    [
        pytest.param([], None, "device_not_found", id="not-found"),
        pytest.param(
            ["192.168.1.90"],
            UnsupportedDeviceError("someModel"),
            "unsupported_device",
            id="unsupported",
        ),
        pytest.param(["192.168.1.90"], Exception, "unknown", id="unexpected"),
    ],
)
async def test_bluetooth_mdns_aborts(
    hass: HomeAssistant,
    mock_provision: AsyncMock,
    mock_read: AsyncMock,
    hosts: list[str],
    side_effect: type[Exception] | Exception | None,
    reason: str,
) -> None:
    """Test the mDNS fallback aborts when no device checks out."""
    mock_provision.return_value = ProvisionResult(SERIAL_NUMBER, None)
    mock_read.side_effect = side_effect
    result = await _start_bluetooth_flow(hass)

    with patch(
        "homeassistant.components.zendure.config_flow.async_find_device",
        _fake_find(hosts),
    ):
        result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client")
async def test_bluetooth_flow_open_network(
    hass: HomeAssistant, mock_provision: AsyncMock
) -> None:
    """Test provisioning to a network without a password."""
    result = await _start_bluetooth_flow(hass)

    result = await _submit_wifi(hass, result, {CONF_SSID: "OpenWiFi"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL_NUMBER
    assert mock_provision.await_args.args[1:] == ("OpenWiFi", "")


async def test_bluetooth_not_zendure(hass: HomeAssistant) -> None:
    """Test an advertiser named Zen... without a Zendure serial number."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=bluetooth_discovery(manufacturer_data={0x004C: b"\x02\x15"}),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_zendure_device"


async def test_bluetooth_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a device that is already set up is not offered again."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=BLUETOOTH_DISCOVERY
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_zeroconf_while_bluetooth_flow_in_progress(hass: HomeAssistant) -> None:
    """Test network discovery of the device does not start a second flow."""
    await _start_bluetooth_flow(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=ZEROCONF_DISCOVERY
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_in_progress"


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client", "mock_provision")
@pytest.mark.parametrize(
    "user_input",
    [
        pytest.param(
            {CONF_SSID: "MyWiFi", CONF_PASSWORD: "short"}, id="short-password"
        ),
        pytest.param({CONF_SSID: "x" * 33, CONF_PASSWORD: "secret123"}, id="long-ssid"),
    ],
)
async def test_bluetooth_invalid_wifi(
    hass: HomeAssistant, user_input: dict[str, str]
) -> None:
    """Test invalid credentials are rejected before connecting to the device."""
    result = await _start_bluetooth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "wifi"
    assert result["errors"] == {"base": "invalid_wifi"}

    result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_zendure")
@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (ProvisioningFailedError, "wifi_join_failed"),
        (ProvisioningTimeoutError, "provision_timeout"),
        (ZendureConnectionError, "cannot_connect_ble"),
    ],
)
async def test_bluetooth_provision_retryable_errors(
    hass: HomeAssistant,
    mock_ble_client: MagicMock,
    mock_provision: AsyncMock,
    side_effect: Exception,
    error: str,
) -> None:
    """Test provisioning errors return to the Wi-Fi form and can be retried."""
    mock_provision.side_effect = side_effect
    result = await _start_bluetooth_flow(hass)

    result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "wifi"
    assert result["errors"] == {"base": error}
    assert get_schema_suggested_value(result["data_schema"].schema, CONF_SSID) == (
        "MyWiFi"
    )
    mock_ble_client.disconnect.assert_awaited_once()

    mock_provision.side_effect = None
    result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.80"}


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client", "mock_provision")
@pytest.mark.parametrize(
    ("target", "kwargs"),
    [
        pytest.param(
            "async_ble_device_from_address", {"return_value": None}, id="not-in-range"
        ),
        pytest.param(
            "establish_connection",
            {"side_effect": BleakError("out of slots")},
            id="connect-failed",
        ),
    ],
)
async def test_bluetooth_cannot_connect(
    hass: HomeAssistant, target: str, kwargs: dict[str, Any]
) -> None:
    """Test a device that cannot be reached over Bluetooth can be retried."""
    result = await _start_bluetooth_flow(hass)

    with patch(f"homeassistant.components.zendure.config_flow.{target}", **kwargs):
        result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect_ble"}

    result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("mock_zendure")
@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        pytest.param(
            {"side_effect": ZendureProtocolError("no provisioning service")},
            "provisioning_not_supported",
            id="no-service",
        ),
        pytest.param(
            {"side_effect": MalformedResponseError("bad reply")},
            "provisioning_not_supported",
            id="malformed-reply",
        ),
    ],
)
async def test_bluetooth_provision_aborts(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    mock_ble_client: MagicMock,
    mock_provision: AsyncMock,
    kwargs: dict[str, Any],
    reason: str,
) -> None:
    """Test provisioning outcomes the user cannot fix from the Wi-Fi form."""
    mock_provision.configure_mock(**kwargs)
    result = await _start_bluetooth_flow(hass)

    with caplog.at_level(logging.DEBUG, logger="homeassistant.components.zendure"):
        result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert f"aborted: {reason}" in caplog.text
    mock_ble_client.disconnect.assert_awaited_once()


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client", "mock_provision")
@pytest.mark.parametrize(
    ("kwargs", "reason", "placeholders"),
    [
        pytest.param(
            {"side_effect": ZendureConnectionError},
            "provisioned_unreachable",
            {"host": "192.168.1.80"},
            id="unreachable",
        ),
        pytest.param(
            {"side_effect": UnsupportedDeviceError("someModel")},
            "unsupported_device",
            None,
            id="unsupported",
        ),
        pytest.param({"side_effect": Exception}, "unknown", None, id="unexpected"),
        pytest.param(
            {
                "return_value": replace(
                    build_snapshot(), serial_number="OTHERDEV0000001"
                )
            },
            "different_device",
            None,
            id="other-device-answers",
        ),
    ],
)
async def test_bluetooth_device_check_after_provision(
    hass: HomeAssistant,
    mock_read: AsyncMock,
    kwargs: dict[str, Any],
    reason: str,
    placeholders: dict[str, str] | None,
) -> None:
    """Test the flow aborts when the provisioned device does not check out."""
    mock_read.configure_mock(**kwargs)
    result = await _start_bluetooth_flow(hass)

    result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert result["description_placeholders"] == placeholders


@pytest.mark.usefixtures("mock_zendure", "mock_ble_client", "mock_provision")
async def test_bluetooth_configured_meanwhile(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the entry is updated if the device was added while provisioning."""
    result = await _start_bluetooth_flow(hass)
    mock_config_entry.add_to_hass(hass)

    result = await _submit_wifi(hass, result, WIFI_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.80"
