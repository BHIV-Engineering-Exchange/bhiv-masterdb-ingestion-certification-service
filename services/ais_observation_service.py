"""Validation and idempotent storage for live AISStream vessel positions."""
import math
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.artifact_store import ArtifactStore


class AISObservationValidationError(ValueError):
    pass


class AISObservationService:
    DATASET_ID = "aisstream_vessel_positions"

    def __init__(self, store: Any | None = None, store_dir: str = "ais_observation_store") -> None:
        self.store = store or ArtifactStore(reports_dir=store_dir)

    @staticmethod
    def validate(observation: Dict[str, Any]) -> Dict[str, Any]:
        required = ("vessel_id", "source", "latitude", "longitude", "received_at_utc")
        missing = [field for field in required if observation.get(field) is None or observation.get(field) == ""]
        if missing:
            raise AISObservationValidationError(f"Missing required field(s): {', '.join(missing)}")
        if observation["source"] != "AISStream":
            raise AISObservationValidationError("source must be AISStream")
        if not isinstance(observation["vessel_id"], str) or not observation["vessel_id"].isdigit():
            raise AISObservationValidationError("vessel_id must be an MMSI string")
        for field, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
            value = observation[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise AISObservationValidationError(f"{field} must be a finite number")
            if not low <= value <= high:
                raise AISObservationValidationError(f"{field} is outside its allowed range")
        for field in ("speed_knots", "course_degrees"):
            value = observation.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise AISObservationValidationError(f"{field} must be a finite number when supplied")
        try:
            datetime.fromisoformat(observation["received_at_utc"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise AISObservationValidationError("received_at_utc must be an ISO-8601 timestamp")
        return dict(observation)

    def ingest(self, feed: Dict[str, Any]) -> Dict[str, Any]:
        if feed.get("source") != "AISStream" or not isinstance(feed.get("observations"), list):
            raise AISObservationValidationError("Expected a normalized AISStream observations feed")
        validated = [self.validate(item) for item in feed["observations"]]
        inserted = updated = 0
        for record in validated:
            record["dataset_id"] = self.DATASET_ID
            record["ingested_at_utc"] = datetime.now(timezone.utc).isoformat()
            if self.store.load(record["vessel_id"]) is None:
                inserted += 1
            else:
                updated += 1
            self.store.save(record["vessel_id"], record)
        return {"dataset_id": self.DATASET_ID, "fetched": len(validated), "inserted": inserted, "updated": updated}

    def get(self, vessel_id: str) -> Dict[str, Any] | None:
        return self.store.load(vessel_id)

    def list(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        records = self.store.list_all()
        records.sort(key=lambda item: (item.get("received_at_utc", ""), item.get("vessel_id", "")), reverse=True)
        return records[offset:offset + limit]
