"""Validation and idempotent persistence for normalized USGS observations."""
from datetime import datetime, timezone
import math
from typing import Any, Dict, List

from services.artifact_store import ArtifactStore


class EarthquakeObservationValidationError(ValueError):
    pass


class EarthquakeObservationService:
    DATASET_ID = "ds-gev-seismic-events"

    def __init__(self, store: Any | None = None, store_dir: str = "earthquake_observation_store"):
        self.store = store or ArtifactStore(reports_dir=store_dir)

    @staticmethod
    def validate(observation: Dict[str, Any]) -> Dict[str, Any]:
        required = ("event_id", "source", "latitude", "longitude", "magnitude", "depth_km", "event_time_utc", "source_url")
        missing = [field for field in required if observation.get(field) is None or observation.get(field) == ""]
        if missing:
            raise EarthquakeObservationValidationError(f"Missing required field(s): {', '.join(missing)}")
        if observation["source"] != "USGS":
            raise EarthquakeObservationValidationError("source must be USGS")
        if not isinstance(observation["event_id"], str) or not observation["event_id"].strip():
            raise EarthquakeObservationValidationError("event_id must be a non-empty string")
        for field in ("latitude", "longitude", "magnitude", "depth_km"):
            value = observation[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EarthquakeObservationValidationError(f"{field} must be a finite number")
        if not -90 <= observation["latitude"] <= 90:
            raise EarthquakeObservationValidationError("latitude must be between -90 and 90")
        if not -180 <= observation["longitude"] <= 180:
            raise EarthquakeObservationValidationError("longitude must be between -180 and 180")
        if not isinstance(observation["source_url"], str) or not observation["source_url"].startswith("https://"):
            raise EarthquakeObservationValidationError("source_url must be an HTTPS URL")
        try:
            datetime.fromisoformat(observation["event_time_utc"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise EarthquakeObservationValidationError("event_time_utc must be an ISO-8601 timestamp")
        return dict(observation)

    def upsert(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        record = self.validate(observation)
        record["dataset_id"] = self.DATASET_ID
        record["ingested_at_utc"] = datetime.now(timezone.utc).isoformat()
        created = self.store.load(record["event_id"]) is None
        self.store.save(record["event_id"], record)
        return {"event_id": record["event_id"], "action": "inserted" if created else "updated"}

    def ingest(self, feed: Dict[str, Any]) -> Dict[str, Any]:
        if feed.get("source") != "USGS" or not isinstance(feed.get("observations"), list):
            raise EarthquakeObservationValidationError("Expected a normalized USGS observations feed")
        validated = [self.validate(item) for item in feed["observations"]]
        outcomes = [self.upsert(item) for item in validated]
        return {"dataset_id": self.DATASET_ID, "fetched": len(outcomes), "inserted": sum(x["action"] == "inserted" for x in outcomes), "updated": sum(x["action"] == "updated" for x in outcomes)}

    def get(self, event_id: str) -> Dict[str, Any] | None:
        return self.store.load(event_id)

    def list(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        items = self.store.list_all()
        items.sort(key=lambda item: (item.get("event_time_utc", ""), item.get("event_id", "")), reverse=True)
        return items[offset:offset + limit]
