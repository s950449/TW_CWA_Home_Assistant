"""Sensors for Taiwan CWA Open Data."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from . import CwaData
from .const import CONF_COUNTY, CONF_STATION_ID, CONF_TOWNSHIP, DOMAIN, MISSING
from .forecast import num as _num


def _text(value: Any) -> str | None:
    return None if value in MISSING else str(value)


def _get(data: dict, *path: str) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _forecast(element: str, field: str = "parameterName") -> Callable[[dict], Any]:
    """First (current) time slot of a 36h forecast element."""

    def fn(data: dict) -> Any:
        for el in data.get("weatherElement", []):
            if el.get("elementName") == element and el.get("time"):
                return el["time"][0].get("parameter", {}).get(field)
        return None

    return fn


@dataclass(frozen=True, kw_only=True)
class CwaSensorDescription(SensorEntityDescription):
    source: str  # "observation" | "forecast" | "earthquake"
    value_fn: Callable[[dict], Any]
    attrs_fn: Callable[[dict], dict[str, Any]] | None = None


SENSORS: tuple[CwaSensorDescription, ...] = (
    # --- Current observation ---
    CwaSensorDescription(
        key="temperature", source="observation", translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_get(d, "WeatherElement", "AirTemperature")),
    ),
    CwaSensorDescription(
        key="humidity", source="observation", translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_get(d, "WeatherElement", "RelativeHumidity")),
    ),
    CwaSensorDescription(
        key="pressure", source="observation", translation_key="pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_get(d, "WeatherElement", "AirPressure")),
    ),
    CwaSensorDescription(
        key="wind_speed", source="observation", translation_key="wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_get(d, "WeatherElement", "WindSpeed")),
    ),
    CwaSensorDescription(
        key="wind_direction", source="observation", translation_key="wind_direction",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        value_fn=lambda d: _num(_get(d, "WeatherElement", "WindDirection")),
    ),
    CwaSensorDescription(
        key="gust", source="observation", translation_key="gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_get(d, "WeatherElement", "GustInfo", "PeakGustSpeed")),
    ),
    CwaSensorDescription(
        key="precipitation", source="observation", translation_key="precipitation",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_get(d, "WeatherElement", "Now", "Precipitation")),
    ),
    CwaSensorDescription(
        key="weather", source="observation", translation_key="weather",
        value_fn=lambda d: _text(_get(d, "WeatherElement", "Weather")),
    ),
    # --- 36-hour forecast (current slot) ---
    CwaSensorDescription(
        key="forecast_weather", source="forecast", translation_key="forecast_weather",
        value_fn=_forecast("Wx"),
    ),
    CwaSensorDescription(
        key="forecast_pop", source="forecast", translation_key="forecast_pop",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: _num(_forecast("PoP")(d)),
    ),
    CwaSensorDescription(
        key="forecast_min_temp", source="forecast", translation_key="forecast_min_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _num(_forecast("MinT")(d)),
    ),
    CwaSensorDescription(
        key="forecast_max_temp", source="forecast", translation_key="forecast_max_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _num(_forecast("MaxT")(d)),
    ),
    CwaSensorDescription(
        key="forecast_comfort", source="forecast", translation_key="forecast_comfort",
        value_fn=_forecast("CI"),
    ),
    # --- Latest earthquake report ---
    CwaSensorDescription(
        key="earthquake_magnitude", source="earthquake", translation_key="earthquake_magnitude",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _num(_get(d, "EarthquakeInfo", "EarthquakeMagnitude", "MagnitudeValue")),
        attrs_fn=lambda d: {
            "origin_time": _get(d, "EarthquakeInfo", "OriginTime"),
            "depth_km": _num(_get(d, "EarthquakeInfo", "FocalDepth")),
            "epicenter": _get(d, "EarthquakeInfo", "Epicenter", "Location"),
            "report": d.get("ReportContent"),
            "url": d.get("Web"),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: CwaData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CwaSensor(coordinator, entry, desc)
        for desc in SENSORS
        if (coordinator := getattr(data, desc.source)) is not None
    )


class CwaSensor(CoordinatorEntity[DataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: CwaSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        description: CwaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"CWA {entry.data[CONF_COUNTY]}{entry.data[CONF_TOWNSHIP]} ({entry.data[CONF_STATION_ID]})",
            manufacturer="Central Weather Administration",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        if fn is None or not self.coordinator.data:
            return None
        return fn(self.coordinator.data)
