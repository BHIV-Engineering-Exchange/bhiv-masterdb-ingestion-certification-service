"""Fetch and validate God’s Eye View's NOAA NHC/CPHC cyclone response."""
import hashlib
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests


GEV_DEFAULT_URL = "http://127.0.0.1:4173"
MAX_STORMS = 32
MAX_FEATURES_PER_KIND = 500
MAX_VERTICES = 25_000
DATASETS = {
    "storms": "noaa_nhc_current_tropical_cyclones",
    "points": "noaa_nhc_cyclone_forecast_points",
    "tracks": "noaa_nhc_cyclone_tracks",
    "cones": "noaa_nhc_cyclone_forecast_cones",
}
SOURCE_IDS = {
    "storms": "src-gev-noaa-nhc-cyclone-status",
    "points": "src-gev-noaa-nhc-cyclone-points",
    "tracks": "src-gev-noaa-nhc-cyclone-tracks",
    "cones": "src-gev-noaa-nhc-cyclone-cones",
}
GIS_LAYERS = {"points": 5, "tracks": 6, "cones": 7}


class CycloneConfigurationError(RuntimeError):
    pass


class CycloneUpstreamError(RuntimeError):
    pass


class CycloneValidationError(ValueError):
    pass


def _base_url() -> str:
    base = os.environ.get("GODS_EYE_VIEW_BASE_URL", GEV_DEFAULT_URL).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise CycloneConfigurationError("God’s Eye View provider URL must be an HTTP(S) origin")
    return base


def _iso(value: Any, *, now: datetime, max_age_hours: float = 12) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z", value):
        raise CycloneValidationError("Cyclone timestamp must be explicit UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CycloneValidationError("Cyclone timestamp is invalid") from None
    if parsed.tzinfo is None or parsed > now + timedelta(minutes=5) or (now - parsed).total_seconds() > max_age_hours * 3600:
        raise CycloneValidationError("Cyclone timestamp is outside its allowed freshness window")
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _finite(value: Any, low: float, high: float, *, optional: bool = False) -> float | None:
    if value is None:
        return None if optional else _invalid("Required cyclone value is missing")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        return _invalid("Cyclone numeric value is outside valid bounds")
    return float(value)


def _invalid(message: str):
    raise CycloneValidationError(message)


def _text(value: Any, *, max_length: int = 80, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > max_length or re.search(r"[\x00-\x1f<>]", value):
        return _invalid("Cyclone text field is invalid")
    return value.strip()


def _position(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return _invalid("Cyclone position is missing")
    return {"longitude": _finite(value.get("longitude"), -180, 180), "latitude": _finite(value.get("latitude"), -90, 90)}


def _coordinates(geometry: Any, kind: str) -> dict[str, Any]:
    allowed = {"points": {"Point"}, "tracks": {"LineString", "MultiLineString"}, "cones": {"Polygon", "MultiPolygon"}}
    if not isinstance(geometry, dict) or geometry.get("type") not in allowed[kind]:
        return _invalid("Cyclone GIS geometry type is invalid")
    total = [0]

    def point(value: Any) -> list[float]:
        if not isinstance(value, list) or len(value) != 2:
            return _invalid("Cyclone GIS coordinate is invalid")
        total[0] += 1
        if total[0] > MAX_VERTICES:
            return _invalid("Cyclone GIS geometry exceeds the vertex limit")
        return [_finite(value[0], -180, 180), _finite(value[1], -90, 90)]

    def line(values: Any, ring: bool = False) -> list[list[float]]:
        minimum = 4 if ring else 2
        if not isinstance(values, list) or not minimum <= len(values) <= 10_000:
            return _invalid("Cyclone GIS path is invalid")
        points = [point(p) for p in values]
        if ring and points[0] != points[-1]:
            return _invalid("Cyclone forecast cone ring is not closed")
        return points

    def parts(values: Any, parse) -> list[Any]:
        if not isinstance(values, list) or not 1 <= len(values) <= 128:
            return _invalid("Cyclone GIS geometry parts are invalid")
        return [parse(v) for v in values]

    geometry_type = geometry["type"]
    raw = geometry.get("coordinates")
    if geometry_type == "Point":
        parsed: Any = point(raw)
    elif geometry_type == "LineString":
        parsed = line(raw)
    elif geometry_type == "MultiLineString":
        parsed = parts(raw, line)
    elif geometry_type == "Polygon":
        parsed = parts(raw, lambda ring: line(ring, ring=True))
    else:
        parsed = parts(raw, lambda polygon: parts(polygon, lambda ring: line(ring, ring=True)))
    return {"type": geometry_type, "coordinates": parsed}


def normalize_cyclone_response(payload: Any, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, dict) or payload.get("unavailable") or payload.get("stale"):
        raise CycloneUpstreamError("God’s Eye View cyclone data is unavailable or stale")
    fetched_ms = payload.get("fetchedAt")
    if isinstance(fetched_ms, bool) or not isinstance(fetched_ms, (int, float)) or not math.isfinite(fetched_ms):
        raise CycloneValidationError("Cyclone response has no valid retrieval timestamp")
    fetched_at = datetime.fromtimestamp(fetched_ms / 1000, timezone.utc)
    if fetched_at > now + timedelta(minutes=5) or (now - fetched_at).total_seconds() > 15 * 60:
        raise CycloneUpstreamError("God’s Eye View cyclone response is stale")
    raw_storms = payload.get("storms")
    if not isinstance(raw_storms, list) or len(raw_storms) > MAX_STORMS:
        raise CycloneValidationError("Cyclone response has an invalid storm list")
    seen: set[str] = set()
    storms: list[dict[str, Any]] = []
    for raw in raw_storms:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not re.fullmatch(r"(?:al|ep|cp)\d{6}", raw["id"]):
            raise CycloneValidationError("Cyclone source ID is invalid")
        source_id = raw["id"]
        if source_id in seen:
            raise CycloneValidationError("Duplicate cyclone source ID")
        seen.add(source_id)
        advisory = _text(raw.get("advisoryNumber"), max_length=4)
        if not re.fullmatch(r"\d{1,3}[A-Z]?", advisory, re.I):
            raise CycloneValidationError("Cyclone advisory number is invalid")
        advisory = advisory.upper().lstrip("0") or "0"
        movement = raw.get("movement")
        if not isinstance(movement, dict):
            raise CycloneValidationError("Cyclone movement metadata is invalid")
        geometry_status = raw.get("geometryStatus")
        if geometry_status not in ("current", "pending", "unavailable"):
            raise CycloneValidationError("Cyclone geometry status is invalid")
        position_at = _iso(raw.get("positionAt"), now=now)
        issued_at = _iso(raw.get("issuedAt"), now=now)
        if geometry_status == "current" and raw.get("geometryAdvisoryNumber") != advisory:
            raise CycloneValidationError("Cyclone geometry advisory does not match current status")
        storm = {
            "source_id": source_id,
            "name": _text(raw.get("name")),
            "classification": _text(raw.get("classification"), max_length=32),
            "basin": _text(raw.get("basin"), max_length=2),
            "position": _position(raw.get("position")),
            "position_at_utc": position_at,
            "advisory_number": advisory,
            "advisory_issued_at_utc": issued_at,
            "wind_speed_kt": _finite(raw.get("windKt"), 0, 300, optional=True),
            "pressure_hpa": _finite(raw.get("pressureHpa"), 800, 1100, optional=True),
            "movement_direction_degrees": _finite(movement.get("directionDegrees"), 0, 360, optional=True),
            "movement_speed_kt": _finite(movement.get("speedKt"), 0, 200, optional=True),
            "advisory_url": _text(raw.get("advisoryUrl"), max_length=256, optional=True),
            "outlook_url": _text(raw.get("outlookUrl"), max_length=256, optional=True),
            "geometry_status": geometry_status,
            "geometry_advisory_number": advisory if geometry_status == "current" else None,
            "forecast_points": [],
            "track": None,
            "cone": None,
        }
        if geometry_status == "current":
            points = raw.get("forecastPoints")
            if not isinstance(points, list) or not points:
                raise CycloneValidationError("Current cyclone geometry has no forecast points")
            parsed_points = []
            seen_tau: set[float] = set()
            for point in points:
                if not isinstance(point, dict):
                    raise CycloneValidationError("Cyclone forecast point is invalid")
                tau = _finite(point.get("tauHours"), 0, 168)
                if tau in seen_tau:
                    raise CycloneValidationError("Cyclone forecast-point lead time is duplicated")
                seen_tau.add(tau)
                parsed_points.append({
                    "position": _position(point.get("position")), "tau_hours": tau,
                    "wind_speed_kt": _finite(point.get("windKt"), 0, 300, optional=True),
                    "gust_kt": _finite(point.get("gustKt"), 0, 350, optional=True),
                })
            storm["forecast_points"] = sorted(parsed_points, key=lambda item: item["tau_hours"])
            storm["track"] = _coordinates(raw.get("track"), "tracks")
            storm["cone"] = _coordinates(raw.get("cone"), "cones")
        storms.append(storm)
    return {
        "source": "NOAA NHC/CPHC via God’s Eye View",
        "fetched_at_utc": fetched_at.isoformat(),
        "coverage": payload.get("coverage"),
        "attribution": payload.get("attribution"),
        "storms": storms,
    }


def fetch_current_cyclones(timeout: float = 20) -> dict[str, Any]:
    url = f"{_base_url()}/api/cyclones"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        if len(response.content) > 4 * 1024 * 1024:
            raise CycloneUpstreamError("God’s Eye View cyclone response exceeded the size limit")
        payload = response.json()
    except CycloneUpstreamError:
        raise
    except (requests.RequestException, ValueError):
        raise CycloneUpstreamError("God’s Eye View cyclone request failed") from None
    return normalize_cyclone_response(payload)
