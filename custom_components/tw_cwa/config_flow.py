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

from .api import CwaAuthError, CwaClient, CwaError, async_get_ssl_context
from .const import (
    CONF_API_KEY,
    CONF_COUNTY,
    CONF_EARTHQUAKE,
    CONF_STATION_DATASET,
    CONF_STATION_ID,
    CONF_TOWNSHIP,
    CONF_TYPHOON,
    COUNTY_DATASETS,
    DATASET_OBSERVATION,
    DATASET_OBSERVATION_AUTO,
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

    async def _client(self) -> CwaClient:
        return CwaClient(
            async_get_clientsession(self.hass),
            self._api_key,
            await async_get_ssl_context(self.hass),
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_key = user_input[CONF_API_KEY].strip()
            try:
                client = await self._client()
                manned = await client.get(DATASET_OBSERVATION)
                auto = await client.get(DATASET_OBSERVATION_AUTO)
            except CwaAuthError:
                errors["base"] = "invalid_auth"
            except CwaError:
                errors["base"] = "cannot_connect"
            else:
                self._stations = [
                    {**st, "_dataset": DATASET_OBSERVATION} for st in manned.get("Station", [])
                ] + [
                    {**st, "_dataset": DATASET_OBSERVATION_AUTO} for st in auto.get("Station", [])
                ]
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
                records = await (await self._client()).get(COUNTY_DATASETS[self._county][0])
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
            dataset, station_id = user_input["station"].split(":", 1)
            return self.async_create_entry(
                title=f"CWA {self._county}{self._township}",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_COUNTY: self._county,
                    CONF_TOWNSHIP: self._township,
                    CONF_STATION_ID: station_id,
                    CONF_STATION_DATASET: dataset,
                    CONF_EARTHQUAKE: user_input[CONF_EARTHQUAKE],
                    CONF_TYPHOON: user_input[CONF_TYPHOON],
                },
            )

        def geo(s: dict[str, Any]) -> dict[str, Any]:
            return s.get("GeoInfo", {})

        in_county = [
            s for s in self._stations if norm_county(geo(s).get("CountyName", "")) == self._county
        ] or self._stations
        # Prefer a station in the same township; manned stations come first in the list.
        default = next((s for s in in_county if geo(s).get("TownName") == self._township), in_county[0])
        kinds = {DATASET_OBSERVATION: "有人站", DATASET_OBSERVATION_AUTO: "自動站"}
        options = [
            SelectOptionDict(
                value=f"{s['_dataset']}:{s['StationId']}",
                label=f"{s['StationName']} ({s['StationId']}) {geo(s).get('TownName', '')} · {kinds[s['_dataset']]}",
            )
            for s in in_county
        ]
        first = not self._async_current_entries()
        # Earthquake/typhoon data is nationwide: enable on one entry only (default: the first).
        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "station", default=f"{default['_dataset']}:{default['StationId']}"
                    ): _select(options),
                    vol.Required(CONF_EARTHQUAKE, default=first): bool,
                    vol.Required(CONF_TYPHOON, default=first): bool,
                }
            ),
        )
