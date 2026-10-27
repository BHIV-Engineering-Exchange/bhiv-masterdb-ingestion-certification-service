"""Validation and idempotent storage for decoded TomTom road-flow segments."""
import hashlib
import math
from datetime import datetime, timezone
from typing import Any

from services.artifact_store import ArtifactStore


class TrafficObservationService:
    DATASET_ID = "tomtom_traffic_flow_segments"

    def __init__(self, store: Any | None = None, store_dir: str = "traffic_observation_store") -> None:
        self.store = store or ArtifactStore(reports_dir=store_dir)

    @staticmethod
    def validate(record: dict[str, Any]) -> dict[str, Any]:
        if record.get("source") != "TomTom Traffic API":
            raise ValueError("source must be TomTom Traffic API")
        tile = record.get("tile")
        if not isinstance(tile, dict) or any(isinstance(tile.get(k), bool) or not isinstance(tile.get(k), int) for k in ("z", "x", "y")):
            raise ValueError("tile must contain integer z, x, and y")
        if not 8 <= tile["z"] <= 16 or any(not 0 <= tile[k] < 2 ** tile["z"] for k in ("x", "y")):
            raise ValueError("tile coordinate is outside supported zoom bounds")
        if record.get("traffic_style") not in ("relative", "absolute"):
            raise ValueError("traffic_style must identify the upstream flow style")
        for field in ("traffic_level", "speed_ratio", "congestion_ratio"):
            value = record.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{field} must be a finite ratio from 0 to 1")
        for field in ("current_speed_kph", "free_flow_speed_kph"):
            value = record.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError(f"{field} must be a finite non-negative number when supplied")
        coords = record.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("coordinates must contain at least two road points")
        for point in coords:
            if not isinstance(point, list) or len(point) < 2:
                raise ValueError("road coordinate must be [longitude, latitude]")
            lon, lat = point[:2]
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lon, lat)) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError("road coordinate is outside valid WGS84 bounds")
        timestamp = record.get("observation_time_utc")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("observation_time_utc must be timezone-aware ISO-8601")
        return dict(record)

    @staticmethod
    def _source_id(record: dict[str, Any]) -> str:
        stable = {k: record.get(k) for k in ("tile", "coordinates", "road_type", "road_coverage", "traffic_style")}
        return "tomtom:" + hashlib.sha256(repr(stable).encode("utf-8")).hexdigest()

    def ingest(self, feed: dict[str, Any]) -> dict[str, Any]:
        if feed.get("source") != "TomTom Traffic API" or not isinstance(feed.get("observations"), list):
            raise ValueError("Expected decoded TomTom traffic-flow segments")
        inserted = updated = skipped = 0
        for raw in feed["observations"]:
            try:
                record = self.validate(raw)
            except (ValueError, TypeError, AttributeError):
                skipped += 1
                continue
            source_id = self._source_id(record)
            record_id = hashlib.sha256(f"{source_id}|{record['observation_time_utc']}".encode("utf-8")).hexdigest()
            record.update({"dataset_id": self.DATASET_ID, "source_id": source_id, "record_id": record_id, "ingested_at_utc": datetime.now(timezone.utc).isoformat()})
            if self.store.load(record_id) is None:
                inserted += 1
            else:
                updated += 1
            self.store.save(record_id, record)
        return {"dataset_id": self.DATASET_ID, "fetched": len(feed["observations"]), "inserted": inserted, "updated": updated, "skipped": skipped}

    def list(self, limit: int = 100, offset: int = 0, tile: dict[str, int] | None = None) -> list[dict[str, Any]]:
        records = self.store.list_all()
        if tile:
            records = [r for r in records if r.get("tile") == tile]
        records.sort(key=lambda r: (r.get("observation_time_utc", ""), r.get("source_id", "")), reverse=True)
        return records[offset:offset + limit]
