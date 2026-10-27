"""Fetch and normalize NASA FIRMS near-real-time active-fire CSV feeds."""
import csv
import io
import os
from datetime import datetime, timezone
from typing import Any

import requests


FIRMS_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")


class FIRMSConfigurationError(RuntimeError):
    pass


class FIRMSUpstreamError(RuntimeError):
    pass


def normalize_fire(row: dict[str, str], source: str) -> dict[str, Any] | None:
    try:
        latitude, longitude = float(row["latitude"]), float(row["longitude"])
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        acq_date = row["acq_date"].strip()
        acq_time = row["acq_time"].strip().zfill(4)
        if len(acq_time) != 4 or not acq_time.isdigit():
            return None
        observed = datetime.strptime(f"{acq_date} {acq_time}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
        satellite = (row.get("satellite") or source).strip()
        # FIRMS area CSV has no single row ID. These stable source fields form
        # a deterministic identifier across repeated fetches.
        source_id = "firms:" + ":".join((source, satellite, observed.strftime("%Y%m%dT%H%MZ"), f"{latitude:.5f}", f"{longitude:.5f}"))
        confidence: Any = (row.get("confidence") or "").strip() or None
        if confidence is not None:
            try:
                confidence = float(confidence) if "." in confidence else int(confidence)
            except ValueError:
                pass
        brightness: Any = row.get("bright_ti4") or row.get("bright_t31") or ""
        try:
            brightness = float(brightness)
        except (TypeError, ValueError):
            brightness = None
        return {
            "source_id": source_id, "source": "NASA FIRMS", "latitude": latitude,
            "longitude": longitude, "observation_time_utc": observed.isoformat(),
            "acquisition_date": acq_date, "acquisition_time": acq_time,
            "satellite": satellite, "confidence": confidence, "brightness": brightness,
            "frp": _number(row.get("frp")), "daynight": row.get("daynight"),
            "source_url": "https://firms.modaps.eosdis.nasa.gov/",
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_active_fires(timeout_seconds: float = 30) -> dict[str, Any]:
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        raise FIRMSConfigurationError("FIRMS_MAP_KEY is not configured")
    observations = []
    try:
        for source in FIRMS_SOURCES:
            response = requests.get(f"{FIRMS_AREA_URL}/{key}/{source}/world/1", timeout=timeout_seconds)
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(response.text))
            if not reader.fieldnames or not {"latitude", "longitude", "acq_date", "acq_time"}.issubset(reader.fieldnames):
                raise FIRMSUpstreamError("NASA FIRMS returned an unexpected CSV schema")
            observations.extend(item for row in reader if (item := normalize_fire(row, source)) is not None)
    except requests.RequestException as exc:
        # Avoid propagating request URLs, which contain the private map key.
        raise FIRMSUpstreamError("NASA FIRMS active-fire request failed") from None
    return {"source": "NASA FIRMS", "dataset": "nasa_firms_active_fires", "record_count": len(observations), "observations": observations}
