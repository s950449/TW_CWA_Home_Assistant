"""One geo_location entity per active tropical cyclone, for the Map card."""
from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CwaData
from .const import DOMAIN
from .typhoon import summarize


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: CwaData = hass.data[DOMAIN][entry.entry_id]
    if data.typhoon is None:
        return

    tracked: dict[str, CwaTyphoon] = {}

    @callback
    def _sync() -> None:
        current = {
            c.get("name") or c.get("name_zh") or "unknown": c
            for c in summarize(data.typhoon.data, hass.config.latitude, hass.config.longitude)
            if "latitude" in c and "longitude" in c
        }
        for key in set(tracked) - set(current):
            hass.async_create_task(tracked.pop(key).async_remove())
        new: list[CwaTyphoon] = []
        for key, cyclone in current.items():
            if key in tracked:
                tracked[key].update_from(cyclone)
            else:
                tracked[key] = CwaTyphoon(entry, key, cyclone)
                new.append(tracked[key])
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(data.typhoon.async_add_listener(_sync))


class CwaTyphoon(GeolocationEvent):
    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_icon = "mdi:weather-hurricane"
    _attr_unit_of_measurement = "km"

    def __init__(self, entry: ConfigEntry, key: str, cyclone: dict[str, Any]) -> None:
        self._attr_unique_id = f"{entry.entry_id}_typhoon_{key}"
        self._set(cyclone)

    def _set(self, c: dict[str, Any]) -> None:
        self._attr_name = " ".join(x for x in (c.get("name_zh"), c.get("name")) if x)
        self._attr_latitude = c["latitude"]
        self._attr_longitude = c["longitude"]
        self._attr_distance = c.get("distance_km")
        self._attrs = {k: v for k, v in c.items() if k not in ("latitude", "longitude", "distance_km")}

    def update_from(self, cyclone: dict[str, Any]) -> None:
        self._set(cyclone)
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs
