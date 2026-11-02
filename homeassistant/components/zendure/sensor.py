"""Sensor platform for Zendure devices."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from zendure import PropertyValue
from zendure.catalog import FaultLevel, fault_codes, lookup_fault

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import ZendureConfigEntry
from .entity import ZendureBatteryEntity, ZendureEntity, ZendureFaultEntity

PARALLEL_UPDATES = 0

FAULT_COUNT = SensorEntityDescription(
    key="fault_count",
    translation_key="fault_count",
    entity_category=EntityCategory.DIAGNOSTIC,
    state_class=SensorStateClass.MEASUREMENT,
)

CURRENT_FAULT_NONE = "none"
# A visible code the fault table does not know.
CURRENT_FAULT_OTHER = "other"

# Fault codes mean different things per model, so each model has its own
# translation key and its own fault names.
CURRENT_FAULT_TRANSLATION_KEYS = {
    "solarflow_2400ac_plus": "current_fault_2400ac_plus",
    "solarflow_5000_max_pro": "current_fault_5000_max_pro",
}

# Faults first, then warnings, then codes without a level.
_LEVEL_ORDER: dict[FaultLevel | None, int] = {
    FaultLevel.FAULT: 0,
    FaultLevel.WARNING: 1,
}


def _current_fault_description(model_key: str) -> SensorEntityDescription | None:
    """Describe the current-fault sensor of a model, if its faults are named."""
    if (translation_key := CURRENT_FAULT_TRANSLATION_KEYS.get(model_key)) is None:
        return None
    return SensorEntityDescription(
        key="current_fault",
        translation_key=translation_key,
        device_class=SensorDeviceClass.ENUM,
        options=[
            CURRENT_FAULT_NONE,
            *(
                str(code)
                for code in fault_codes(model_key)
                if lookup_fault(model_key, code).visible
            ),
            CURRENT_FAULT_OTHER,
        ],
    )


# Raw state codes reported by packState (device) and state (battery pack).
PACK_STATES = {0: "standby", 1: "charging", 2: "discharging"}


def _pack_state(value: PropertyValue) -> str | None:
    """Map a raw pack state code to its option, or unknown."""
    if not isinstance(value, int):
        return None
    return PACK_STATES.get(value)


@dataclass(frozen=True, kw_only=True)
class ZendureSensorEntityDescription(SensorEntityDescription):
    """Describes a Zendure sensor entity."""

    value_fn: Callable[[PropertyValue], StateType] = lambda value: value


def _power(key: str, translation_key: str) -> ZendureSensorEntityDescription:
    """Describe an instantaneous power sensor."""
    return ZendureSensorEntityDescription(
        key=key,
        translation_key=translation_key,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    )


DEVICE_SENSORS: tuple[ZendureSensorEntityDescription, ...] = (
    ZendureSensorEntityDescription(
        key="electricLevel",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _power("solarInputPower", "solar_input_power"),
    _power("solarPower1", "solar_power_1"),
    _power("solarPower2", "solar_power_2"),
    _power("solarPower3", "solar_power_3"),
    _power("solarPower4", "solar_power_4"),
    _power("outputHomePower", "output_home_power"),
    _power("gridInputPower", "grid_input_power"),
    _power("gridOffPower", "grid_off_power"),
    _power("outputPackPower", "battery_charge_power"),
    _power("packInputPower", "battery_discharge_power"),
    ZendureSensorEntityDescription(
        key="remainOutTime",
        translation_key="remaining_discharge_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ZendureSensorEntityDescription(
        key="packState",
        translation_key="pack_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(PACK_STATES.values()),
        value_fn=_pack_state,
    ),
    ZendureSensorEntityDescription(
        key="hyperTmp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ZendureSensorEntityDescription(
        key="packNum",
        translation_key="pack_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ZendureSensorEntityDescription(
        key="inverseMaxPower",
        translation_key="max_output_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ZendureSensorEntityDescription(
        key="chargeMaxLimit",
        translation_key="max_charge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ZendureSensorEntityDescription(
        key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

BATTERY_SENSORS: tuple[ZendureSensorEntityDescription, ...] = (
    ZendureSensorEntityDescription(
        key="socLevel",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _power("power", "battery_power"),
    ZendureSensorEntityDescription(
        key="batcur",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ZendureSensorEntityDescription(
        key="totalVol",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    ZendureSensorEntityDescription(
        key="maxVol",
        translation_key="max_cell_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ZendureSensorEntityDescription(
        key="minVol",
        translation_key="min_cell_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ZendureSensorEntityDescription(
        key="maxTemp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ZendureSensorEntityDescription(
        key="state",
        translation_key="pack_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(PACK_STATES.values()),
        value_fn=_pack_state,
    ),
    ZendureSensorEntityDescription(
        key="softVersion",
        translation_key="software_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZendureConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Zendure sensors based on a config entry."""
    coordinator = entry.runtime_data
    reported = coordinator.data.properties
    entities: list[SensorEntity] = [
        ZendureSensorEntity(coordinator, description)
        for description in DEVICE_SENSORS
        if description.key in reported
    ]
    if coordinator.client.faults_supported is not False:
        entities.append(ZendureFaultCountSensorEntity(coordinator, FAULT_COUNT))
        if current_fault := _current_fault_description(coordinator.data.model_key):
            entities.append(ZendureCurrentFaultSensorEntity(coordinator, current_fault))
    async_add_entities(entities)

    known_batteries: set[str] = set()

    @callback
    def _async_add_new_batteries() -> None:
        """Add sensors for battery packs seen for the first time."""
        new = [
            battery
            for battery in coordinator.data.batteries
            if battery.serial_number not in known_batteries
        ]
        if not new:
            return
        known_batteries.update(battery.serial_number for battery in new)
        async_add_entities(
            ZendureBatterySensorEntity(coordinator, description, battery.serial_number)
            for battery in new
            for description in BATTERY_SENSORS
            if description.key in battery.properties
        )

    _async_add_new_batteries()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_batteries))


class ZendureSensorEntity(ZendureEntity, SensorEntity):
    """A sensor of the Zendure device."""

    entity_description: ZendureSensorEntityDescription

    @property
    @override
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.raw_value)


class ZendureCurrentFaultSensorEntity(ZendureFaultEntity, SensorEntity):
    """The most severe fault the device reports, by its fault code."""

    @property
    @override
    def native_value(self) -> str:
        """Return the code of the most severe visible fault, or none."""
        if not (faults := self.visible_faults):
            return CURRENT_FAULT_NONE
        # min keeps the first of equals, so the device's order breaks ties.
        fault = min(faults, key=lambda f: _LEVEL_ORDER.get(f.level, len(_LEVEL_ORDER)))
        if (state := str(fault.code)) in (self.options or ()):
            return state
        return CURRENT_FAULT_OTHER


class ZendureFaultCountSensorEntity(ZendureFaultEntity, SensorEntity):
    """The number of faults the device reports that the user should see."""

    @property
    @override
    def native_value(self) -> int:
        """Return the number of visible faults."""
        return len(self.visible_faults)


class ZendureBatterySensorEntity(ZendureBatteryEntity, SensorEntity):
    """A sensor of one battery pack."""

    entity_description: ZendureSensorEntityDescription

    @property
    @override
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.raw_value)
