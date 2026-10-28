"""Validation and time-aware persistence for normalized ADS-B observations."""
import math
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.artifact_store import ArtifactStore


class AircraftObservationValidationError(ValueError):
    pass


class AircraftObservationService:
    DATASET_ID = "adsb_military_aircraft_observations"

    def __init__(self, store: Any | None = None, store_dir: str = "aircraft_observation_store") -> None:
        self.store = store or ArtifactStore(reports_dir=store_dir)

    @staticmethod
    def validate(observation: Dict[str, Any]) -> Dict[str, Any]:
        required = ("aircraft_hex_id", "source", "latitude", "longitude", "source_url")
        missing = [field for field in required if observation.get(field) is None or observation.get(field) == ""]
        if missing:
            raise AircraftObservationValidationError(f"Missing required field(s): {', '.join(missing)}")
        if observation["source"] != "adsb.lol":
            raise AircraftObservationValidationError("source must be adsb.lol")
        aircraft_hex_id = observation["aircraft_hex_id"]
        if not isinstance(aircraft_hex_id, str) or len(aircraft_hex_id) != 6 or any(char not in "0123456789ABCDEF" for char in aircraft_hex_id.upper()):
            raise AircraftObservationValidationError("aircraft_hex_id must be a six-character hexadecimal identifier")
        for field, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
            value = observation[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise AircraftObservationValidationError(f"{field} is invalid")
        observed = observation.get("observation_time_utc")
        if observed is not None:
            try:
                datetime.fromisoformat(observed.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                raise AircraftObservationValidationError("observation_time_utc must be an ISO-8601 timestamp when supplied")
        return dict(observation)

    @staticmethod
    def _record_id(record: Dict[str, Any]) -> str:
        observation_time = record.get("observation_time_utc")
        if not observation_time:
            return record["aircraft_hex_id"]
        # ArtifactStore's JSON backend uses keys as filenames on Windows.
        # Keep this deterministic while excluding filesystem-reserved ':' chars.
        safe_time = observation_time.replace(":", "_").replace("+", "plus")
        return f"{record['aircraft_hex_id']}__{safe_time}"

    def ingest(self, feed: Dict[str, Any]) -> Dict[str, Any]:
        if feed.get("source") != "adsb.lol" or not isinstance(feed.get("observations"), list):
            raise AircraftObservationValidationError("Expected a normalized adsb.lol observations feed")
        validated = [self.validate(item) for item in feed["observations"]]
        inserted = updated = 0
        for record in validated:
            record["dataset_id"] = self.DATASET_ID
            record["ingested_at_utc"] = datetime.now(timezone.utc).isoformat()
            record_id = self._record_id(record)
            record["record_id"] = record_id
            if self.store.load(record_id) is None:
                inserted += 1
            else:
                updated += 1
            self.store.save(record_id, record)
        return {"dataset_id": self.DATASET_ID, "fetched": len(validated), "inserted": inserted, "updated": updated}

    def get(self, record_id: str) -> Dict[str, Any] | None:
        return self.store.load(record_id)

    def list(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        records = self.store.list_all()
        records.sort(key=lambda item: (item.get("observation_time_utc") or item.get("ingested_at_utc", ""), item["aircraft_hex_id"]), reverse=True)
        return records[offset:offset + limit]
