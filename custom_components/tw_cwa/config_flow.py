"""Config flow for Taiwan CWA Open Data."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import CwaAuthError, CwaClient, CwaError
from .const import (
    CONF_API_KEY,
    CONF_COUNTY,
    CONF_EARTHQUAKE,
    CONF_STATION_ID,
    CONF_TOWNSHIP,
    COUNTY_DATASETS,
    DATASET_OBSERVATION,
    DOMAIN,
)
from .forecast import norm_county


def _select(options: list[SelectOptionDict]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN, sort=True)
    )


class CwaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._api_key = ""
        self._county = ""
        self._township = ""
        self._townships: list[str] = []
        self._stations: list[dict[str, Any]] = []

    def _client(self) -> CwaClient:
        return CwaClient(async_get_clientsession(self.hass), self._api_key)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_key = user_input[CONF_API_KEY].strip()
            try:
                records = await self._client().get(DATASET_OBSERVATION)
            except CwaAuthError:
                errors["base"] = "invalid_auth"
            except CwaError:
                errors["base"] = "cannot_connect"
            else:
                self._stations = records.get("Station", [])
                return await self.async_step_county()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_county(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._county = user_input[CONF_COUNTY]
            try:
                records = await self._client().get(COUNTY_DATASETS[self._county][0])
            except CwaAuthError:
                errors["base"] = "invalid_auth"
            except CwaError:
                errors["base"] = "cannot_connect"
            else:
                groups = records.get("Locations") or []
                if not groups or norm_county(groups[0].get("LocationsName", "")) != self._county:
                    errors["base"] = "dataset_mismatch"
                else:
                    self._townships = [
                        loc["LocationName"] for loc in groups[0].get("Location", [])
                    ]
                    return await self.async_step_township()

        return self.async_show_form(
            step_id="county",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COUNTY): _select(
                        [SelectOptionDict(value=c, label=c) for c in COUNTY_DATASETS]
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_township(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._township = user_input[CONF_TOWNSHIP]
            await self.async_set_unique_id(f"{self._county}{self._township}")
            self._abort_if_unique_id_configured()
            return await self.async_step_station()

        return self.async_show_form(
            step_id="township",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOWNSHIP): _select(
                        [SelectOptionDict(value=t, label=t) for t in self._townships]
                    )
                }
            ),
        )

    async def async_step_station(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"CWA {self._county}{self._township}",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_COUNTY: self._county,
                    CONF_TOWNSHIP: self._township,
                    **user_input,
                },
            )

        in_county = [
            s for s in self._stations
            if norm_county(s.get("GeoInfo", {}).get("CountyName", "")) == self._county
        ] or self._stations
        default = next(
            (s for s in in_county if s.get("GeoInfo", {}).get("TownName") == self._township),
            in_county[0],
        )
        options = [
            SelectOptionDict(
                value=s["StationId"],
                label=f"{s['StationName']} ({s['StationId']}) "
                f"{s.get('GeoInfo', {}).get('TownName', '')}",
            )
            for s in in_county
        ]
        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATION_ID, default=default["StationId"]): _select(options),
                    # Earthquake data is not location specific; default on for the first entry only.
                    vol.Required(
                        CONF_EARTHQUAKE, default=not self._async_current_entries()
                    ): bool,
                }
            ),
        )
