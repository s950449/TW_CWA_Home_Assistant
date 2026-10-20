"""Parsing of CWA township forecast (F-D0047-xxx) records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import MISSING

HOURLY_COUNT = 24
DAILY_COUNT = 7
_HOLD = timedelta(hours=3)


def num(value: Any) -> float | None:
    if value in MISSING:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def norm_county(name: str) -> str:
    return name.replace("台", "臺")


def _parse_time(raw: Any) -> datetime | None:
    dt = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_util.get_time_zone("Asia/Taipei"))
    return dt


@dataclass
class Point:
    """Values valid at one instant (end is None) or over [start, end)."""

    start: datetime
    end: datetime | None
    values: dict[str, Any] = field(default_factory=dict)


def parse_points(location: dict[str, Any]) -> list[Point]:
    """Flatten WeatherElement/Time/ElementValue into a time-sorted list."""
    points: list[Point] = []
    for element in location.get("WeatherElement", []):
        for t in element.get("Time", []):
            start = _parse_time(t.get("DataTime") or t.get("StartTime"))
            if start is None:
                continue
            values: dict[str, Any] = {}
            raw = t.get("ElementValue", [])
            for item in [raw] if isinstance(raw, dict) else raw:
                values.update({k: v for k, v in item.items() if v not in MISSING})
            points.append(Point(start, _parse_time(t.get("EndTime")), values))
    points.sort(key=lambda p: p.start)
    return points


def condition_from(text: str | None, hour: int) -> str | None:
    """Map a CWA weather phenomenon string to a Home Assistant condition."""
    if not text:
        return None
    if "雷" in text:
        return "lightning-rainy"
    if "雪" in text:
        return "snowy"
    if any(k in text for k in ("大雨", "豪雨")):
        return "pouring"
    if "雨" in text:
        return "rainy"
    if "霧" in text:
        return "fog"
    if "多雲" in text:
        return "cloudy" if "陰" in text else "partlycloudy"
    if "陰" in text:
        return "cloudy"
    if "晴" in text:
        return "clear-night" if hour >= 18 or hour < 6 else "sunny"
    return None


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def hourly_forecast(location: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Next HOURLY_COUNT hours; instants are held up to 3h, spans fill their range."""
    points = parse_points(location)
    instants = [p for p in points if p.end is None]
    spans = [p for p in points if p.end is not None]
    first = now.replace(minute=0, second=0, microsecond=0)
    out: list[dict[str, Any]] = []
    for i in range(HOURLY_COUNT):
        h = first + timedelta(hours=i)
        v: dict[str, Any] = {}
        for p in instants:
            if p.start <= h < p.start + _HOLD:
                v.update(p.values)
        for p in spans:
            if p.start <= h < p.end:
                v.update(p.values)
        if not v:
            continue
        wind_dir = v.get("WindDirection")
        out.append(
            _compact(
                {
                    "datetime": h.isoformat(),
                    "condition": condition_from(v.get("Weather"), h.hour),
                    "native_temperature": num(v.get("Temperature")),
                    "native_apparent_temperature": num(v.get("ApparentTemperature")),
                    "native_dew_point": num(v.get("DewPoint")),
                    "humidity": num(v.get("RelativeHumidity")),
                    "precipitation_probability": num(v.get("ProbabilityOfPrecipitation")),
                    "wind_bearing": num(wind_dir) if num(wind_dir) is not None else wind_dir,
                    "native_wind_speed": num(v.get("WindSpeed")),
                }
            )
        )
    return out


def daily_forecast(location: dict[str, Any]) -> list[dict[str, Any]]:
    """Group the 12-hourly 1-week forecast by local date."""
    days: dict[Any, list[Point]] = {}
    for p in parse_points(location):
        days.setdefault(dt_util.as_local(p.start).date(), []).append(p)

    out: list[dict[str, Any]] = []
    for date, pts in sorted(days.items())[:DAILY_COUNT]:
        highs = [x for p in pts if (x := num(p.values.get("MaxTemperature", p.values.get("Temperature")))) is not None]
        lows = [x for p in pts if (x := num(p.values.get("MinTemperature", p.values.get("Temperature")))) is not None]
        pops = [x for p in pts if (x := num(p.values.get("ProbabilityOfPrecipitation"))) is not None]
        day = next((p for p in pts if 6 <= dt_util.as_local(p.start).hour < 18), pts[0])
        out.append(
            _compact(
                {
                    "datetime": dt_util.start_of_local_day(date).isoformat(),
                    "condition": condition_from(day.values.get("Weather"), 12),
                    "native_temperature": max(highs) if highs else None,
                    "native_templow": min(lows) if lows else None,
                    "precipitation_probability": max(pops) if pops else None,
                    "humidity": num(day.values.get("RelativeHumidity")),
                    "native_wind_speed": num(day.values.get("WindSpeed")),
                }
            )
        )
    return out
