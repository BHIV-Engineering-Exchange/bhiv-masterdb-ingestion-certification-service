"""Fetch and normalize publicly broadcast ADS-B records from adsb.lol."""
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests


ADSB_MILITARY_URL = "https://api.adsb.lol/v2/mil"


class AircraftUpstreamError(RuntimeError):
    pass


class AircraftUpstreamRateLimitError(AircraftUpstreamError):
    pass


def _iso_timestamp(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    seconds = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def normalize_aircraft(record: Dict[str, Any], observed_at_utc: str | None) -> Dict[str, Any] | None:
    aircraft_hex_id = record.get("hex")
    latitude, longitude = record.get("lat"), record.get("lon")
    if not isinstance(aircraft_hex_id, str) or not aircraft_hex_id:
        return None
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return None
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    altitude = record.get("alt_baro")
    normalized = {
        "aircraft_hex_id": aircraft_hex_id.upper(),
        "source": "adsb.lol",
        "latitude": latitude,
        "longitude": longitude,
        "observation_time_utc": observed_at_utc,
        "source_url": ADSB_MILITARY_URL,
        "callsign": record.get("flight").strip() if isinstance(record.get("flight"), str) else None,
        "altitude_baro_ft": altitude if isinstance(altitude, (int, float)) and not isinstance(altitude, bool) else None,
        "ground_speed_kts": record.get("gs") if isinstance(record.get("gs"), (int, float)) and not isinstance(record.get("gs"), bool) else None,
        "track_degrees": record.get("track") if isinstance(record.get("track"), (int, float)) and not isinstance(record.get("track"), bool) else None,
        "metadata": {key: record[key] for key in ("r", "t", "type", "alt_geom", "seen", "seen_pos") if key in record},
    }
    return {key: value for key, value in normalized.items() if value is not None}


def fetch_military_aircraft(timeout_seconds: float = 20) -> Dict[str, Any]:
    try:
        response = requests.get(ADSB_MILITARY_URL, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise AircraftUpstreamError("adsb.lol military feed request failed") from exc
    if response.status_code == 429:
        raise AircraftUpstreamRateLimitError("adsb.lol military feed rate limit reached")
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AircraftUpstreamError("adsb.lol military feed returned an invalid response") from exc
    observed_at_utc = _iso_timestamp(payload.get("now"))
    observations = [
        normalized
        for item in payload.get("ac", [])
        if isinstance(item, dict)
        for normalized in [normalize_aircraft(item, observed_at_utc)]
        if normalized is not None
    ]
    return {
        "source": "adsb.lol",
        "dataset": "adsb_military_aircraft_observations",
        "record_count": len(observations),
        "observations": observations,
    }
