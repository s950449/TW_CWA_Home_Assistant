"""Summarise W-C0034-005 (active tropical cyclones)."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

from .forecast import num


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


def _fix(fix: dict[str, Any]) -> dict[str, Any]:
    out = {
        "time": fix.get("DateTime"),
        "latitude": num(fix.get("CoordinateLatitude")),
        "longitude": num(fix.get("CoordinateLongitude")),
        "max_wind_speed": num(fix.get("MaxWindSpeed")),
        "max_gust_speed": num(fix.get("MaxGustSpeed")),
        "pressure": num(fix.get("Pressure")),
        "moving_speed": num(fix.get("MovingSpeed")),
        "moving_direction": fix.get("MovingDirection"),
    }
    if "ForecastHour" in fix:
        out["forecast_hour"] = num(fix.get("ForecastHour"))
        out["initial_time"] = fix.get("InitialTime")
    return {k: v for k, v in out.items() if v is not None}


def summarize(data: dict[str, Any], home_lat: float, home_lon: float) -> list[dict[str, Any]]:
    """One dict per active cyclone, with the latest fix and a slim forecast track."""
    cyclones = ((data or {}).get("TropicalCyclones") or {}).get("TropicalCyclone") or []
    out: list[dict[str, Any]] = []
    for c in cyclones:
        fixes = (c.get("AnalysisData") or {}).get("Fix") or []
        if not fixes:
            continue
        latest = _fix(max(fixes, key=lambda f: f.get("DateTime") or ""))
        item: dict[str, Any] = {
            "name": c.get("TyphoonName"),
            "name_zh": c.get("CwaTyphoonName"),
            "number": c.get("CwaTyNo"),
            "td_number": c.get("CwaTdNo"),
            **latest,
            "forecast": [_fix(f) for f in (c.get("ForecastData") or {}).get("Fix") or []],
        }
        if "latitude" in latest and "longitude" in latest:
            item["distance_km"] = round(
                haversine_km(home_lat, home_lon, latest["latitude"], latest["longitude"])
            )
        out.append({k: v for k, v in item.items() if v not in (None, "")})
    return out
