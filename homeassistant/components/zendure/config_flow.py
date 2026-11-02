"""Config flow to configure the Zendure integration."""

import asyncio
from typing import Any, override

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
import probatio
from zendure import (
    DeviceSnapshot,
    ProvisioningFailedError,
    ProvisioningTimeoutError,
    UnsupportedDeviceError,
    ValidationError,
    ZendureConnectionError,
    ZendureError,
    create_local_client,
)
from zendure.ble import (
    async_provision_wifi,
    build_provision_request,
    parse_serial_number,
)
from zendure.catalog import lookup_device
from zendure.protocols.local_http.discovery import parse_mdns_hostname

from homeassistant.components import zeroconf
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_SSID, DOMAIN, LOGGER, MDNS_TIMEOUT
from .discovery import async_find_device

STEP_WIFI_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_SSID): TextSelector(
            TextSelectorConfig(autocomplete="off")
        ),
        probatio.Optional(CONF_PASSWORD, default=""): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="new-password"
            )
        ),
    }
)


class _WifiError(Exception):
    """Provisioning failed in a way the user can retry from the Wi-Fi form."""

    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.error = error


class ZendureFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a Zendure config flow."""

    VERSION = 1

    _host: str
    _title: str
    _discovery_info: BluetoothServiceInfoBleak
    _ssid: str = ""
    _password: str = ""
    _wifi_error: str | None = None
    _reported_host: str | None = None
    _provision_task: asyncio.Task[str | None] | None = None
    _connect_task: asyncio.Task[tuple[str, DeviceSnapshot]] | None = None

    async def _async_read_device(self, host: str) -> DeviceSnapshot:
        """Read the device once to prove it answers and learn its identity."""
        async with create_local_client(
            host, async_get_clientsession(self.hass)
        ) as client:
            return await client.async_refresh()

    async def _async_validate(
        self, host: str, errors: dict[str, str]
    ) -> DeviceSnapshot | None:
        """Read the device, recording a form error instead of raising."""
        try:
            return await self._async_read_device(host)
        except ValidationError:
            errors[CONF_HOST] = "invalid_host"
        except UnsupportedDeviceError as err:
            LOGGER.debug(
                "Device at %s reports unsupported product %r", host, err.product
            )
            errors["base"] = "unsupported_device"
        except ZendureError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        return None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            if snapshot := await self._async_validate(host, errors):
                await self.async_set_unique_id(
                    snapshot.serial_number, raise_on_progress=False
                )
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=_title(snapshot), data={CONF_HOST: host}
                )
        else:
            user_input = {}

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_HOST, default=user_input.get(CONF_HOST)
                    ): TextSelector(TextSelectorConfig(autocomplete="off")),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a change of the device's address."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        host = reconfigure_entry.data[CONF_HOST]

        if user_input is not None:
            host = user_input[CONF_HOST]
            if snapshot := await self._async_validate(host, errors):
                await self.async_set_unique_id(snapshot.serial_number)
                self._abort_if_unique_id_mismatch(reason="different_device")
                return self.async_update_reload_and_abort(
                    reconfigure_entry, data_updates={CONF_HOST: host}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_HOST, default=host): TextSelector(
                        TextSelectorConfig(autocomplete="off")
                    ),
                }
            ),
            errors=errors,
        )

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery of a Zendure device."""
        if not (parsed := parse_mdns_hostname(discovery_info.hostname)):
            return self.async_abort(reason="not_zendure_device")
        product, serial_number = parsed
        # Reject other models from the advertised name, without an HTTP read.
        try:
            lookup_device(product)
        except UnsupportedDeviceError:
            LOGGER.debug(
                "Ignoring %s at %s: unsupported product %r",
                serial_number,
                discovery_info.host,
                product,
            )
            return self.async_abort(reason="unsupported_device")

        await self.async_set_unique_id(serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.host})

        errors: dict[str, str] = {}
        if not (snapshot := await self._async_validate(discovery_info.host, errors)):
            return self.async_abort(reason=errors.get("base", "cannot_connect"))
        if snapshot.serial_number != serial_number:
            return self.async_abort(reason="different_device")

        self._host = discovery_info.host
        self._title = _title(snapshot)
        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._title, data={CONF_HOST: self._host}
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": self._title, "host": self._host},
        )

    @override
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a Zendure device advertising over Bluetooth."""
        serial_number = parse_serial_number(discovery_info.manufacturer_data)
        LOGGER.debug(
            "BLE discovery %s (%s) rssi=%s connectable=%s manufacturer_data=%s "
            "service_uuids=%s -> serial %s",
            discovery_info.name,
            discovery_info.address,
            discovery_info.rssi,
            discovery_info.connectable,
            {hex(k): v.hex() for k, v in discovery_info.manufacturer_data.items()},
            discovery_info.service_uuids,
            serial_number,
        )
        if not serial_number:
            return self.async_abort(reason="not_zendure_device")

        await self.async_set_unique_id(serial_number)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_wifi()

    async def async_step_wifi(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Wi-Fi network the device should join."""
        errors: dict[str, str] = {}
        if self._wifi_error:
            errors["base"], self._wifi_error = self._wifi_error, None

        if user_input is not None:
            self._ssid = user_input[CONF_SSID]
            password = user_input[CONF_PASSWORD]
            try:
                build_provision_request(self._ssid, password)
            except ValidationError:
                errors["base"] = "invalid_wifi"
            else:
                self._password = password
                return await self.async_step_provision()

        return self.async_show_form(
            step_id="wifi",
            data_schema=self.add_suggested_values_to_schema(
                STEP_WIFI_DATA_SCHEMA, {CONF_SSID: self._ssid}
            ),
            description_placeholders={"name": self._discovery_info.name},
            errors=errors,
        )

    async def async_step_provision(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send the Wi-Fi credentials and wait until the device is online."""
        if not self._provision_task:
            self._provision_task = self.hass.async_create_task(
                self._async_provision(), eager_start=False
            )
        if not self._provision_task.done():
            return self.async_show_progress(
                step_id="provision",
                progress_action="provisioning",
                progress_task=self._provision_task,
            )
        return self.async_show_progress_done(next_step_id="provision_done")

    async def async_step_provision_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Go on to find the device, or back to the Wi-Fi form on a retryable error."""
        assert self._provision_task is not None
        task, self._provision_task = self._provision_task, None
        self._password = ""
        address = self._discovery_info.address
        try:
            host = task.result()
        except _WifiError as err:
            LOGGER.debug(
                "Provisioning %s failed, retry allowed: %s", address, err.error
            )
            self._wifi_error = err.error
            return await self.async_step_wifi()
        except AbortFlow as err:
            LOGGER.debug("Provisioning %s aborted: %s", address, err.reason)
            raise
        LOGGER.debug("Provisioning %s succeeded, reported host %s", address, host)
        self._reported_host = host
        return await self.async_step_connect()

    async def async_step_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait until the provisioned device answers on the network."""
        if not self._connect_task:
            self._connect_task = self.hass.async_create_task(
                self._async_connect(), eager_start=False
            )
        if not self._connect_task.done():
            return self.async_show_progress(
                step_id="connect",
                progress_action="connecting",
                progress_task=self._connect_task,
            )
        return self.async_show_progress_done(next_step_id="connect_done")

    async def async_step_connect_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry for the device found on the network."""
        assert self._connect_task is not None
        task, self._connect_task = self._connect_task, None
        try:
            host, snapshot = task.result()
        except AbortFlow as err:
            LOGGER.debug("Connecting to %s aborted: %s", self.unique_id, err.reason)
            raise
        LOGGER.debug("Device %s answers at %s", self.unique_id, host)

        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        return self.async_create_entry(title=_title(snapshot), data={CONF_HOST: host})

    async def _async_provision(self) -> str | None:
        """Hand the Wi-Fi credentials over BLE; return the reported host, if any.

        Raises _WifiError for errors the user can retry, AbortFlow otherwise.
        """
        address = self._discovery_info.address
        if not (ble_device := async_ble_device_from_address(self.hass, address)):
            raise _WifiError("cannot_connect_ble")
        try:
            client = await establish_connection(
                BleakClient, ble_device, self._discovery_info.name
            )
        except BleakError as err:
            LOGGER.debug("Could not connect to %s: %s", address, err)
            raise _WifiError("cannot_connect_ble") from err
        try:
            result = await async_provision_wifi(client, self._ssid, self._password)
        except ProvisioningFailedError as err:
            raise _WifiError("wifi_join_failed") from err
        except ProvisioningTimeoutError as err:
            raise _WifiError("provision_timeout") from err
        except ZendureConnectionError as err:
            LOGGER.debug("Provisioning link to %s failed: %s", address, err)
            raise _WifiError("cannot_connect_ble") from err
        except ZendureError as err:
            LOGGER.warning("Device %s cannot be provisioned: %s", address, err)
            raise AbortFlow("provisioning_not_supported") from err
        finally:
            await client.disconnect()

        if result.serial_number != self.unique_id:
            # Some firmware reports a cloud id here; identity is checked over HTTP.
            LOGGER.debug(
                "Reply deviceId %s differs from advertised serial %s",
                result.serial_number,
                self.unique_id,
            )
        return result.host

    async def _async_connect(self) -> tuple[str, DeviceSnapshot]:
        """Read the device at its reported host, or find it over mDNS."""
        if host := self._reported_host:
            errors: dict[str, str] = {}
            if not (snapshot := await self._async_validate(host, errors)):
                if errors.get("base") == "cannot_connect":
                    raise AbortFlow(
                        "provisioned_unreachable",
                        description_placeholders={"host": host},
                    )
                raise AbortFlow(errors.get("base", "unknown"))
            if snapshot.serial_number != self.unique_id:
                raise AbortFlow("different_device")
            return host, snapshot

        LOGGER.debug("No host reported, looking for %s over mDNS", self.unique_id)
        assert self.unique_id is not None
        found = await async_find_device(
            await zeroconf.async_get_async_instance(self.hass),
            self.unique_id,
            self._async_check_candidate,
            MDNS_TIMEOUT,
        )
        if found is None:
            raise AbortFlow("device_not_found")
        return found

    async def _async_check_candidate(self, host: str) -> DeviceSnapshot | None:
        """Return the snapshot if ``host`` is this device; keep waiting otherwise."""
        errors: dict[str, str] = {}
        if not (snapshot := await self._async_validate(host, errors)):
            if errors.get("base") == "cannot_connect":
                return None
            raise AbortFlow(errors.get("base", "unknown"))
        if snapshot.serial_number != self.unique_id:
            LOGGER.debug(
                "%s is %s, not %s", host, snapshot.serial_number, self.unique_id
            )
            return None
        return snapshot


def _title(snapshot: DeviceSnapshot) -> str:
    """Return the entry title for a device."""
    return lookup_device(snapshot.product_raw).display_name
