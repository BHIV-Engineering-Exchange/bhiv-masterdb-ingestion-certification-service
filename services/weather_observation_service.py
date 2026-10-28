"""Validation and idempotent persistence for point-sampled weather records."""
import hashlib
import math
from datetime import datetime, timezone
from typing import Any

from services.artifact_store import ArtifactStore


class WeatherObservationService:
    WIND_DATASETS = {"GFS": "gev_gfs_wind_forecasts", "ECMWF": "gev_ecmwf_wind_forecasts"}
    CURRENT_DATASET = "open_meteo_current_surface_weather"
    WEATHER_FIELDS = (
        "temperature_2m_c", "apparent_temperature_c", "relative_humidity_2m_pct", "dew_point_2m_c",
        "pressure_msl_hpa", "surface_pressure_hpa", "wind_speed_10m_mps", "wind_direction_10m_degrees",
        "wind_gusts_10m_mps", "precipitation_mm", "rain_mm", "showers_mm", "snowfall_cm",
        "cloud_cover_pct", "visibility_m", "weather_code", "elevation_m",
    )

    def __init__(self, store: Any | None = None, store_dir: str = "weather_observation_store") -> None:
        self.store = store or ArtifactStore(reports_dir=store_dir)

    @staticmethod
    def _aware(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.tzinfo is not None and parsed.utcoffset() is not None
        except (ValueError, TypeError):
            return False

    @classmethod
    def validate(cls, row: dict[str, Any], *, forecast: bool) -> dict[str, Any]:
        if not isinstance(row, dict) or row.get("is_forecast") is not forecast:
            raise ValueError("Weather record forecast classification is invalid")
        for field, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} is invalid")
        time_fields = ("run_time_utc", "forecast_valid_at_utc") if forecast else ("observed_at_utc",)
        if any(not cls._aware(row.get(field)) for field in time_fields):
            raise ValueError("Weather timestamps must be timezone-aware ISO-8601")
        if forecast:
            if row.get("record_type") != "FORECAST" or row.get("model") not in cls.WIND_DATASETS:
                raise ValueError("Wind record must identify a supported forecast model")
            for field in ("wind_u_mps", "wind_v_mps", "wind_speed_mps", "wind_direction_degrees"):
                value = row.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{field} must be finite")
            if row["wind_speed_mps"] < 0 or not 0 <= row["wind_direction_degrees"] <= 360:
                raise ValueError("Wind speed or direction is outside its valid range")
            numeric = ("temperature_2m_c", "pressure_msl_hpa")
        else:
            if row.get("record_type") != "CURRENT_CONDITIONS" or row.get("source") != "Open-Meteo":
                raise ValueError("Current weather record must identify Open-Meteo conditions")
            numeric = cls.WEATHER_FIELDS
        for field in numeric:
            value = row.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"{field} must be finite when supplied")
        for field in ("relative_humidity_2m_pct", "cloud_cover_pct"):
            value = row.get(field)
            if value is not None and not 0 <= value <= 100:
                raise ValueError(f"{field} must be between 0 and 100")
        direction = row.get("wind_direction_10m_degrees")
        if direction is not None and not 0 <= direction <= 360:
            raise ValueError("wind_direction_10m_degrees is outside its valid range")
        return dict(row)

    def ingest(self, feed: dict[str, Any], *, forecast: bool) -> dict[str, Any]:
        if not isinstance(feed, dict) or not isinstance(feed.get("observations"), list):
            raise ValueError("Expected normalized weather observations")
        rows = [self.validate(row, forecast=forecast) for row in feed["observations"]]
        inserted = updated = 0
        dataset = self.WIND_DATASETS[feed["model"]] if forecast else self.CURRENT_DATASET
        for row in rows:
            identity_time = row["forecast_valid_at_utc"] if forecast else row["observed_at_utc"]
            identity = f"{dataset}|{row['latitude']:.5f}|{row['longitude']:.5f}|{identity_time}"
            record_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            row.update({"dataset_id": dataset, "record_id": record_id, "ingested_at_utc": datetime.now(timezone.utc).isoformat()})
            if self.store.load(record_id) is None:
                inserted += 1
            else:
                updated += 1
            self.store.save(record_id, row)
        return {"dataset_id": dataset, "fetched": len(rows), "inserted": inserted, "updated": updated,
                "record_ids": [row["record_id"] for row in rows]}

    def get(self, record_id: str) -> dict[str, Any] | None:
        return self.store.load(record_id)

    def list(self, dataset_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if dataset_id not in (*self.WIND_DATASETS.values(), self.CURRENT_DATASET):
            raise ValueError("Unknown weather dataset")
        rows = [row for row in self.store.list_all() if row.get("dataset_id") == dataset_id]
        time_field = "forecast_valid_at_utc" if dataset_id in self.WIND_DATASETS.values() else "observed_at_utc"
        rows.sort(key=lambda row: row.get(time_field, ""), reverse=True)
        return rows[offset:offset + limit]
