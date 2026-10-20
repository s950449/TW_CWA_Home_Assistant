"""Weather entity: current observation + township hourly/daily forecast."""
from __future__ import annotations

from typing import Any

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import CwaData
from .const import CONF_COUNTY, CONF_STATION_ID, CONF_TOWNSHIP, DOMAIN
from .forecast import condition_from, daily_forecast, hourly_forecast, num


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([CwaWeather(hass.data[DOMAIN][entry.entry_id], entry)])


def _obs(data: dict, *path: str) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


class CwaWeather(CoordinatorEntity, WeatherEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )

    def __init__(self, data: CwaData, entry: ConfigEntry) -> None:
        super().__init__(data.observation)
        self._data = data
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"CWA {entry.data[CONF_COUNTY]}{entry.data[CONF_TOWNSHIP]} "
            f"({entry.data[CONF_STATION_ID]})",
            manufacturer="Central Weather Administration",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for coordinator, kind in (
            (self._data.town_3d, "hourly"),
            (self._data.town_week, "daily"),
        ):
            self.async_on_remove(coordinator.async_add_listener(self._forecast_listener(kind)))

    def _forecast_listener(self, kind: str):
        def _update() -> None:
            self.hass.async_create_task(self.async_update_listeners((kind,)))

        return _update

    # --- current conditions (observation station) ---
    @property
    def _obs(self) -> dict:
        return self.coordinator.data or {}

    @property
    def native_temperature(self) -> float | None:
        return num(_obs(self._obs, "WeatherElement", "AirTemperature"))

    @property
    def humidity(self) -> float | None:
        return num(_obs(self._obs, "WeatherElement", "RelativeHumidity"))

    @property
    def native_pressure(self) -> float | None:
        return num(_obs(self._obs, "WeatherElement", "AirPressure"))

    @property
    def native_wind_speed(self) -> float | None:
        return num(_obs(self._obs, "WeatherElement", "WindSpeed"))

    @property
    def native_wind_gust_speed(self) -> float | None:
        return num(_obs(self._obs, "WeatherElement", "GustInfo", "PeakGustSpeed"))

    @property
    def wind_bearing(self) -> float | None:
        return num(_obs(self._obs, "WeatherElement", "WindDirection"))

    @property
    def condition(self) -> str | None:
        text = _obs(self._obs, "WeatherElement", "Weather")
        if (cond := condition_from(text if text != "-99" else None, dt_util.now().hour)) is not None:
            return cond
        # Observation has no phenomenon (e.g. unmanned station): use the forecast.
        hourly = self._hourly()
        return hourly[0].get("condition") if hourly else None

    # --- forecasts (township) ---
    def _hourly(self) -> list[Forecast]:
        loc = self._data.town_3d.data
        return hourly_forecast(loc, dt_util.now()) if loc else []

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        return self._hourly()

    async def async_forecast_daily(self) -> list[Forecast] | None:
        loc = self._data.town_week.data
        return daily_forecast(loc) if loc else []
