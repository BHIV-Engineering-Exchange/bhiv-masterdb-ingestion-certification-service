
"""Fetch and normalize live earthquake data from the USGS GeoJSON feed."""

from datetime import datetime, timezone
from typing import Any

import requests


USGS_FEED_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)


def fetch_earthquakes() -> dict[str, Any]:
    """Fetch today's earthquake records and return normalized observations."""

    response = requests.get(USGS_FEED_URL, timeout=20)
    response.raise_for_status()
    data = response.json()

    observations = []

    for feature in data.get("features", []):
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []

        if len(coordinates) < 3:
            continue

        longitude, latitude, depth = coordinates[:3]

        if not isinstance(latitude, (int, float)):
            continue
        if not isinstance(longitude, (int, float)):
            continue

        timestamp_ms = properties.get("time")
        event_time = None

        if isinstance(timestamp_ms, (int, float)):
            event_time = datetime.fromtimestamp(
                timestamp_ms / 1000, tz=timezone.utc
            ).isoformat()

        event_id = feature.get("id")
        magnitude = properties.get("mag")
        source_url = properties.get("url")
        if (
            not isinstance(event_id, str) or not event_id
            or not isinstance(magnitude, (int, float))
            or not isinstance(depth, (int, float))
            or event_time is None
            or not isinstance(source_url, str)
        ):
            continue

        observations.append(
            {
                "event_id": event_id,
                "source": "USGS",
                "place": properties.get("place"),
                "magnitude": magnitude,
                "longitude": longitude,
                "latitude": latitude,
                "depth_km": depth,
                "event_time_utc": event_time,
                "source_url": source_url,
            }
        )

    return {
        "source": "USGS",
        "dataset": "earthquake_events",
        "record_count": len(observations),
        "observations": observations,
    }
