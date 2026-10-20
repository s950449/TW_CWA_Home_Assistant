# Taiwan CWA Open Data for Home Assistant

HACS custom integration for the [中央氣象署開放資料平台](https://opendata.cwa.gov.tw) REST API.
One config entry = one township (鄉鎮市區). Add the integration again for each additional township.

## Entities

| Entity | Dataset | Notes | Poll |
|---|---|---|---|
| `weather.*` | `O-A0003-001` + `F-D0047-xxx` | Current conditions from the observation station; **hourly forecast (next 24 h)** and **daily forecast (1 week)** for the township | 10 min / 60 min |
| Observation sensors | `O-A0003-001` (manned) or `O-A0001-001` (automatic stations) | temperature, humidity, pressure, wind speed/direction, peak gust, precipitation, weather | 10 min |
| 36h county sensors | `F-C0032-001` | weather, rain probability, min/max temp, comfort (county level) | 60 min |
| Typhoons | `W-C0034-005` | `sensor` = number of active tropical cyclones in the NW Pacific (attributes: name, position, wind, pressure, movement, forecast track, distance to your home). One `geo_location` entity per cyclone for the Map card. Optional; enabled by default on the first entry only | 30 min |
| Latest earthquake | `E-A0015-001` | magnitude (+ time, depth, epicenter, report URL as attributes). Optional; enabled by default on the first entry only | 10 min |

Hourly forecast: temperature, apparent temperature, dew point, humidity and wind are hourly in the 3-day
dataset; rain probability and weather phenomenon are published per 3 hours and repeated for each hour in that span.
Use it with `weather.get_forecasts` (`type: hourly` / `daily`) or the weather forecast card.

Requests per day: ~216 per township entry (observation 144, forecasts 72) + ~144 for earthquakes and ~48 for typhoons on the one entry that enables them.
Two townships with both enabled ≈ 624/day (free tier: 1000/day).

### Typhoon map

```yaml
type: map
geo_location_sources:
  - tw_cwa
default_zoom: 5
```
The Map card uses OpenStreetMap-based tiles. Automations can use `sensor.*active_tropical_cyclones` and its `nearest_distance_km` attribute.

When the station reports no reading (`-99`), the `weather` entity falls back to the current-hour forecast for temperature, humidity and wind speed.

## Install (HACS)

1. HACS → ⋮ → Custom repositories → add this repo's URL, category **Integration**.
2. Download "Taiwan CWA Open Data", restart Home Assistant.
3. Settings → Devices & services → Add integration → **Taiwan CWA Open Data**.
4. Enter the API key, then choose county → township → observation station (manned or automatic; a station in the same township is preselected). Earthquake and typhoon sensors are nationwide: keep them enabled on one entry only.

## Notes

- Replace the `documentation`/`issue_tracker` URLs and `codeowners` in `manifest.json` with your own repo.
- Missing readings (`-99`) are reported as unknown.
- County → dataset IDs (`F-D0047-001…087`) are in `const.py`; the config flow checks the returned county name and reports `dataset_mismatch` if one is wrong.
- Version 0.1.0 entries (before township support) must be removed and re-added.
