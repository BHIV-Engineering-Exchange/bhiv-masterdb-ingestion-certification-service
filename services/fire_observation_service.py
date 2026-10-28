"""Validation and idempotent persistence for normalized FIRMS fire detections."""
import math
import hashlib
from datetime import datetime, timezone
from typing import Any

from services.artifact_store import ArtifactStore


class FireObservationService:
    DATASET_ID = "nasa_firms_active_fires"

    def __init__(self, store: Any | None = None, store_dir: str = "fire_observation_store") -> None:
        self.store = store or ArtifactStore(reports_dir=store_dir)

    @staticmethod
    def validate(item: dict[str, Any]) -> dict[str, Any]:
        if item.get("source") != "NASA FIRMS":
            raise ValueError("source must be NASA FIRMS")
        if not isinstance(item.get("source_id"), str) or not item["source_id"].strip():
            raise ValueError("source_id must be a non-empty string")
        for field, low, high in (("latitude", -90, 90), ("longitude", -180, 180)):
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} is invalid")
        try:
            timestamp = datetime.fromisoformat(item["observation_time_utc"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError("observation_time_utc must be a timezone-aware ISO-8601 timestamp")
        return dict(item)

    def ingest(self, feed: dict[str, Any]) -> dict[str, Any]:
        if feed.get("source") != "NASA FIRMS" or not isinstance(feed.get("observations"), list):
            raise ValueError("Expected a normalized NASA FIRMS observations feed")
        inserted = updated = skipped = 0
        for raw in feed["observations"]:
            try:
                record = self.validate(raw)
            except (ValueError, AttributeError, TypeError):
                skipped += 1
                continue
            record["dataset_id"] = self.DATASET_ID
            record["ingested_at_utc"] = datetime.now(timezone.utc).isoformat()
            # Hash external identifiers so keys remain valid on Windows stores.
            key = hashlib.sha256(f"{record['source_id']}|{record['observation_time_utc']}".encode("utf-8")).hexdigest()
            record["record_id"] = key
            if self.store.load(key) is None:
                inserted += 1
            else:
                updated += 1
            self.store.save(key, record)
        return {"dataset_id": self.DATASET_ID, "fetched": len(feed["observations"]), "inserted": inserted, "updated": updated, "skipped": skipped}

    def list(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        records = self.store.list_all()
        records.sort(key=lambda row: (row.get("observation_time_utc", ""), row.get("source_id", "")), reverse=True)
        return records[offset:offset + limit]
