"""Taiwan CWA Open Data integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CwaAuthError, CwaClient, CwaError, async_get_ssl_context
from .const import (
    CONF_API_KEY,
    CONF_COUNTY,
    CONF_EARTHQUAKE,
    CONF_STATION_ID,
    CONF_TOWNSHIP,
    COUNTY_DATASETS,
    DATASET_EARTHQUAKE,
    DATASET_FORECAST,
    DATASET_OBSERVATION,
    DOMAIN,
    SCAN_EARTHQUAKE,
    SCAN_FORECAST,
    SCAN_OBSERVATION,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "weather"]


@dataclass
class CwaData:
    """Coordinators for one config entry."""

    observation: DataUpdateCoordinator
    forecast: DataUpdateCoordinator  # county 36h
    town_3d: DataUpdateCoordinator  # township, hourly/3-hourly for 3 days
    town_week: DataUpdateCoordinator  # township, 12-hourly for 1 week
    earthquake: DataUpdateCoordinator | None


def _make_coordinator(
    hass: HomeAssistant,
    entry: ConfigEntry,
    name: str,
    interval: timedelta,
    fetch,
) -> DataUpdateCoordinator:
    async def _update() -> dict[str, Any]:
        try:
            return await fetch()
        except CwaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CwaError as err:
            raise UpdateFailed(str(err)) from err

    return DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=f"{DOMAIN} {name}",
        update_method=_update,
        update_interval=interval,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = CwaClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        await async_get_ssl_context(hass),
    )
    station_id = entry.data[CONF_STATION_ID]
    county = entry.data[CONF_COUNTY]
    township = entry.data[CONF_TOWNSHIP]
    id_3d, id_week = COUNTY_DATASETS[county]

    async def fetch_observation() -> dict[str, Any]:
        records = await client.get(DATASET_OBSERVATION, StationId=station_id)
        stations = records.get("Station") or []
        if not stations:
            raise CwaError(f"Station {station_id} not found")
        return stations[0]

    async def fetch_forecast() -> dict[str, Any]:
        records = await client.get(DATASET_FORECAST, locationName=county)
        locations = records.get("location") or []
        if not locations:
            raise CwaError(f"No forecast for {county}")
        return locations[0]

    def township_fetcher(dataset: str):
        async def fetch() -> dict[str, Any]:
            records = await client.get(dataset, LocationName=township)
            for group in records.get("Locations") or []:
                if group.get("Location"):
                    return group["Location"][0]
            raise CwaError(f"No township forecast for {county}{township} ({dataset})")

        return fetch

    async def fetch_earthquake() -> dict[str, Any]:
        records = await client.get(DATASET_EARTHQUAKE, limit=1)
        quakes = records.get("Earthquake") or []
        return quakes[0] if quakes else {}

    data = CwaData(
        observation=_make_coordinator(
            hass, entry, "observation", SCAN_OBSERVATION, fetch_observation
        ),
        forecast=_make_coordinator(hass, entry, "forecast", SCAN_FORECAST, fetch_forecast),
        town_3d=_make_coordinator(
            hass, entry, "township 3d", SCAN_FORECAST, township_fetcher(id_3d)
        ),
        town_week=_make_coordinator(
            hass, entry, "township week", SCAN_FORECAST, township_fetcher(id_week)
        ),
        earthquake=(
            _make_coordinator(hass, entry, "earthquake", SCAN_EARTHQUAKE, fetch_earthquake)
            if entry.data.get(CONF_EARTHQUAKE)
            else None
        ),
    )
    for coordinator in (
        data.observation,
        data.forecast,
        data.town_3d,
        data.town_week,
        data.earthquake,
    ):
        if coordinator is not None:
            await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
