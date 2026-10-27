"""Fetch God's Eye View wind forecasts and Open-Meteo current conditions."""
import math
import os
import struct
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


GEV_DEFAULT_URL = "http://127.0.0.1:4173"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEV_MODELS = {"gfs": "gfs", "ecmwf": "ifs"}
MAX_LOCATIONS = 100
MAX_GRID_POINTS = 1_000_000
MAX_GRID_BYTES = MAX_GRID_POINTS * 12
OPEN_METEO_CURRENT_FIELDS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,"
    "pressure_msl,surface_pressure,precipitation,rain,showers,snowfall,"
    "weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,visibility,is_day"
)


class WeatherConfigurationError(RuntimeError):
    pass


class WeatherUpstreamError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _iso_utc(value: Any, *, naive_is_utc: bool = False) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            if not naive_is_utc:
                return None
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


def validate_location(location: Any) -> dict[str, float]:
    if not isinstance(location, dict):
        raise ValueError("Each location must contain latitude and longitude")
    lat, lon = _number(location.get("latitude")), _number(location.get("longitude"))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Location coordinates must be finite WGS84 latitude/longitude")
    return {"latitude": lat, "longitude": lon}


def _gev_url() -> str:
    base = os.environ.get("GODS_EYE_VIEW_BASE_URL", GEV_DEFAULT_URL).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise WeatherConfigurationError("GODS_EYE_VIEW_BASE_URL must be an HTTP(S) origin")
    return base


def _request_json(url: str, *, timeout: float) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise WeatherUpstreamError("Weather source request failed or returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise WeatherUpstreamError("Weather source returned an unexpected response shape")
    return payload


def _wind_grid(base: str, model: str, overlay: str) -> tuple[dict[str, Any], bytes]:
    provider_model = GEV_MODELS[model]
    manifest_url = f"{base}/api/wind/manifest?model={provider_model}&overlay={overlay}"
    manifest = _request_json(manifest_url, timeout=55)
    if manifest.get("unavailable") or manifest.get("stale") or manifest.get("model") != provider_model:
        raise WeatherUpstreamError(f"God's Eye View {model.upper()} forecast is unavailable")
    cycle = manifest.get("cycle")
    grid = manifest.get("grid")
    grid_path = manifest.get("gridUrl")
    if not isinstance(cycle, dict) or not isinstance(grid, dict) or not isinstance(grid_path, str):
        raise WeatherUpstreamError("God's Eye View returned an incomplete wind manifest")
    if not grid_path.startswith("/api/wind/grid/") or ".." in grid_path:
        raise WeatherUpstreamError("God's Eye View returned an invalid wind-grid path")
    if overlay != "none" and manifest.get("scalar", {}).get("kind") != overlay:
        # GEV keeps wind available when an optional same-cycle scalar is missing.
        if not manifest.get("scalarError"):
            raise WeatherUpstreamError("God's Eye View returned mismatched forecast scalar metadata")
    nx, ny = grid.get("nx"), grid.get("ny")
    if (isinstance(nx, bool) or isinstance(ny, bool) or not isinstance(nx, int) or not isinstance(ny, int)
            or nx < 1 or ny < 1 or nx * ny > MAX_GRID_POINTS):
        raise WeatherUpstreamError("God's Eye View returned invalid forecast-grid dimensions")
    if not all(_number(grid.get(field)) is not None for field in ("lo1", "la1", "dx", "dy")):
        raise WeatherUpstreamError("God's Eye View returned invalid forecast-grid coordinates")
    if manifest.get("units") != "m/s" or manifest.get("level") != "10 m above ground":
        raise WeatherUpstreamError("God's Eye View returned unsupported wind units or level")
    grid_url = urljoin(base + "/", grid_path.lstrip("/"))
    if urlparse(grid_url).netloc != urlparse(base).netloc:
        raise WeatherUpstreamError("God's Eye View returned a cross-origin grid URL")
    try:
        response = requests.get(grid_url, timeout=55)
        response.raise_for_status()
        body = response.content
    except requests.RequestException:
        raise WeatherUpstreamError("God's Eye View forecast-grid request failed") from None
    if not body or len(body) > MAX_GRID_BYTES:
        raise WeatherUpstreamError("God's Eye View returned an invalid forecast-grid size")
    expected_values = nx * ny * (3 if manifest.get("scalar") else 2)
    if len(body) != expected_values * 4:
        raise WeatherUpstreamError("God's Eye View forecast-grid byte length did not match its manifest")
    return manifest, body


def _sample_grid(body: bytes, grid: dict[str, Any], latitude: float, longitude: float, *, scalar: bool) -> tuple[float, float, float | None]:
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = float(grid["dx"]), float(grid["dy"])
    if dx <= 0 or dy <= 0:
        raise WeatherUpstreamError("God's Eye View returned invalid forecast-grid spacing")
    # GEV resamples to a north-to-south global equirectangular grid with lo1=0, la1=90.
    x = int(round((longitude % 360) / dx)) % nx
    y = max(0, min(ny - 1, int(round((90 - latitude) / dy))))
    index = y * nx + x
    count = nx * ny
    u = struct.unpack_from("<f", body, index * 4)[0]
    v = struct.unpack_from("<f", body, (count + index) * 4)[0]
    scalar_value = struct.unpack_from("<f", body, (count * 2 + index) * 4)[0] if scalar else None
    if not math.isfinite(u) or not math.isfinite(v) or (scalar_value is not None and not math.isfinite(scalar_value)):
        raise WeatherUpstreamError("God's Eye View returned non-finite forecast values")
    return u, v, scalar_value


def fetch_wind_forecasts(model: str, locations: list[dict[str, Any]], timeout_seconds: float = 55) -> dict[str, Any]:
    if model not in GEV_MODELS:
        raise ValueError("model must be gfs or ecmwf")
    if not isinstance(locations, list) or not 1 <= len(locations) <= MAX_LOCATIONS:
        raise ValueError(f"locations must contain 1 to {MAX_LOCATIONS} points")
    points = [validate_location(location) for location in locations]
    base = _gev_url()
    # The GEV provider's temperature and pressure overlays carry their scalar
    # alongside the same-cycle U/V vectors. Its manifest advertises omissions.
    temp_manifest, temp_body = _wind_grid(base, model, "temperature")
    pressure_manifest, pressure_body = _wind_grid(base, model, "pressure")
    for other in (pressure_manifest,):
        if other.get("cycle") != temp_manifest.get("cycle") or other.get("grid") != temp_manifest.get("grid"):
            raise WeatherUpstreamError("God's Eye View overlay grids do not match the wind forecast cycle")
    records = []
    for point in points:
        u, v, temperature = _sample_grid(temp_body, temp_manifest["grid"], point["latitude"], point["longitude"], scalar=bool(temp_manifest.get("scalar")))
        _, _, pressure = _sample_grid(pressure_body, pressure_manifest["grid"], point["latitude"], point["longitude"], scalar=bool(pressure_manifest.get("scalar")))
        cycle = temp_manifest["cycle"]
        valid = _iso_utc(cycle.get("validIso"))
        run = _iso_utc(cycle.get("runIso"))
        if not valid or not run:
            raise WeatherUpstreamError("God's Eye View forecast timestamps are invalid")
        speed = math.hypot(u, v)
        direction = (math.degrees(math.atan2(-u, -v)) + 360) % 360
        records.append({
            "source": "God's Eye View wind provider", "model": model.upper(),
            "record_type": "FORECAST", "is_forecast": True,
            "latitude": point["latitude"], "longitude": point["longitude"],
            "run_time_utc": run, "forecast_valid_at_utc": valid,
            "forecast_hour": cycle.get("forecastHour"),
            "wind_level": "10 m above ground", "wind_u_mps": u, "wind_v_mps": v,
            "wind_speed_mps": speed, "wind_direction_degrees": direction,
            "temperature_2m_c": temperature, "pressure_msl_hpa": pressure,
            "temperature_available": temperature is not None,
            "pressure_available": pressure is not None,
            "provider_fetched_at_utc": _iso_utc(datetime.fromtimestamp(temp_manifest.get("fetchedAt", 0) / 1000, tz=timezone.utc).isoformat()),
        })
    return {"source": "God's Eye View wind provider", "model": model.upper(), "dataset": f"gev_{model}_wind_forecasts", "observations": records, "record_count": len(records), "cycle": temp_manifest["cycle"]}


def normalize_open_meteo(payload: dict[str, Any], requested: dict[str, float]) -> dict[str, Any]:
    current = payload.get("current")
    if not isinstance(current, dict):
        raise ValueError("Open-Meteo response is missing current conditions")
    observed = _iso_utc(current.get("time"), naive_is_utc=True)
    if not observed:
        raise ValueError("Open-Meteo returned an invalid current timestamp")
    latitude, longitude = _number(payload.get("latitude")), _number(payload.get("longitude"))
    if latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Open-Meteo returned invalid coordinates")
    units = payload.get("current_units") if isinstance(payload.get("current_units"), dict) else {}
    wind_speed = _number(current.get("wind_speed_10m"))
    wind_unit = units.get("wind_speed_10m")
    if wind_speed is not None and wind_unit == "km/h":
        wind_speed /= 3.6
    elif wind_speed is not None and wind_unit not in ("m/s", "ms"):
        raise ValueError("Open-Meteo returned an unsupported wind-speed unit")
    weather = {
        "temperature_2m_c": _number(current.get("temperature_2m")),
        "apparent_temperature_c": _number(current.get("apparent_temperature")),
        "relative_humidity_2m_pct": _number(current.get("relative_humidity_2m")),
        "dew_point_2m_c": _number(current.get("dew_point_2m")),
        "pressure_msl_hpa": _number(current.get("pressure_msl")),
        "surface_pressure_hpa": _number(current.get("surface_pressure")),
        "wind_speed_10m_mps": wind_speed,
        "wind_direction_10m_degrees": _number(current.get("wind_direction_10m")),
        "wind_gusts_10m_mps": _number(current.get("wind_gusts_10m")),
        "precipitation_mm": _number(current.get("precipitation")),
        "rain_mm": _number(current.get("rain")),
        "showers_mm": _number(current.get("showers")),
        "snowfall_cm": _number(current.get("snowfall")),
        "cloud_cover_pct": _number(current.get("cloud_cover")),
        "visibility_m": _number(current.get("visibility")),
        "weather_code": _number(current.get("weather_code")),
        "is_day": bool(current["is_day"]) if current.get("is_day") in (0, 1, False, True) else None,
    }
    if not any(value is not None for value in weather.values()):
        raise ValueError("Open-Meteo returned no usable current weather fields")
    return {
        "source": "Open-Meteo", "record_type": "CURRENT_CONDITIONS", "is_forecast": False,
        "latitude": latitude, "longitude": longitude,
        "requested_latitude": requested["latitude"], "requested_longitude": requested["longitude"],
        "observed_at_utc": observed, "source_model": payload.get("model") or "best_match",
        "elevation_m": _number(payload.get("elevation")),
        "time_basis": "UTC", "wind_speed_unit": "m/s", "temperature_unit": "degC",
        "pressure_unit": units.get("pressure_msl") or "hPa",
        **weather,
    }


def fetch_open_meteo_current(locations: list[dict[str, Any]], timeout_seconds: float = 20) -> dict[str, Any]:
    if not isinstance(locations, list) or not 1 <= len(locations) <= MAX_LOCATIONS:
        raise ValueError(f"locations must contain 1 to {MAX_LOCATIONS} points")
    observations = []
    for raw in locations:
        point = validate_location(raw)
        params = {
            "latitude": f"{point['latitude']:.5f}", "longitude": f"{point['longitude']:.5f}",
            "current": OPEN_METEO_CURRENT_FIELDS, "timezone": "UTC",
            "temperature_unit": "celsius", "wind_speed_unit": "ms",
            "precipitation_unit": "mm", "timeformat": "iso8601",
        }
        try:
            response = requests.get(OPEN_METEO_URL, params=params, timeout=timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Invalid response")
            observations.append(normalize_open_meteo(payload, point))
        except requests.RequestException:
            raise WeatherUpstreamError("Open-Meteo current-weather request failed") from None
        except ValueError as exc:
            raise WeatherUpstreamError(f"Open-Meteo response validation failed: {exc}") from None
    return {"source": "Open-Meteo", "dataset": "open_meteo_current_surface_weather", "observations": observations, "record_count": len(observations)}
