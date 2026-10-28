"""Persist normalized NHC cyclone status rows and separate GIS feature records."""
import hashlib
import math
from datetime import datetime, timezone
from typing import Any

from integrations.noaa_cyclone_connector import DATASETS
from services.artifact_store import ArtifactStore


class CycloneObservationValidationError(ValueError):
    pass


class CycloneObservationService:
    SNAPSHOT_ID = "cyclone-feed-current-snapshot"

    def __init__(self, store: Any | None = None, store_dir: str = "cyclone_observation_store") -> None:
        self.store = store or ArtifactStore(reports_dir=store_dir)

    @staticmethod
    def _id(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_position(position: Any) -> bool:
        if not isinstance(position, dict):
            return False
        lon, lat = position.get("longitude"), position.get("latitude")
        return (
            not isinstance(lon, bool) and isinstance(lon, (int, float)) and math.isfinite(lon) and -180 <= lon <= 180
            and not isinstance(lat, bool) and isinstance(lat, (int, float)) and math.isfinite(lat) and -90 <= lat <= 90
        )

    @classmethod
    def _validate_storm(cls, storm: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(storm, dict) or not isinstance(storm.get("source_id"), str) or not storm["source_id"]:
            raise CycloneObservationValidationError("Cyclone source identifier is required")
        if not storm.get("name") or not storm.get("classification") or not storm.get("basin"):
            raise CycloneObservationValidationError("Cyclone name, classification, and basin are required")
        if not cls._valid_position(storm.get("position")):
            raise CycloneObservationValidationError("Cyclone position is invalid")
        for field in ("position_at_utc", "advisory_issued_at_utc"):
            try:
                timestamp = datetime.fromisoformat(storm[field].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, KeyError, AttributeError):
                raise CycloneObservationValidationError(f"{field} must be timezone-aware ISO-8601") from None
        return dict(storm)

    @staticmethod
    def _write(store: Any, record: dict[str, Any]) -> tuple[str, str]:
        record_id = record["record_id"]
        action = "updated" if store.load(record_id) is not None else "inserted"
        record["ingested_at_utc"] = datetime.now(timezone.utc).isoformat()
        store.save(record_id, record)
        return record_id, action

    def ingest(self, feed: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(feed, dict) or feed.get("source") != "NOAA NHC/CPHC via God’s Eye View" or not isinstance(feed.get("storms"), list):
            raise CycloneObservationValidationError("Expected normalized NHC/CPHC cyclone feed")
        status_rows: list[dict[str, Any]] = []
        point_rows: list[dict[str, Any]] = []
        track_rows: list[dict[str, Any]] = []
        cone_rows: list[dict[str, Any]] = []
        for raw in feed["storms"]:
            storm = self._validate_storm(raw)
            status_id = self._id(f"storm|{storm['source_id']}|{storm['position_at_utc']}")
            status = {key: value for key, value in storm.items() if key not in ("forecast_points", "track", "cone")}
            status.update({"dataset_id": DATASETS["storms"], "record_id": status_id, "source": feed["source"], "fetched_at_utc": feed["fetched_at_utc"]})
            status_rows.append(status)
            if storm.get("geometry_status") != "current":
                continue
            advisory = storm["advisory_number"]
            for point in storm["forecast_points"]:
                if not self._valid_position(point.get("position")):
                    raise CycloneObservationValidationError("Cyclone forecast point is invalid")
                point_id = self._id(f"point|{storm['source_id']}|{advisory}|{point['tau_hours']}")
                point_rows.append({
                    "dataset_id": DATASETS["points"], "record_id": point_id,
                    "source_id": storm["source_id"], "advisory_number": advisory,
                    "tau_hours": point["tau_hours"], "geometry": {"type": "Point", "coordinates": [point["position"]["longitude"], point["position"]["latitude"]]},
                    "properties": {"wind_speed_kt": point.get("wind_speed_kt"), "gust_kt": point.get("gust_kt")},
                    "observed_at_utc": storm["advisory_issued_at_utc"], "source": feed["source"],
                })
            for kind, geometry, rows in (("track", storm.get("track"), track_rows), ("cone", storm.get("cone"), cone_rows)):
                if not isinstance(geometry, dict) or not geometry.get("type") or not isinstance(geometry.get("coordinates"), (list, dict)):
                    raise CycloneObservationValidationError(f"Cyclone {kind} geometry is invalid")
                feature_id = self._id(f"{kind}|{storm['source_id']}|{advisory}")
                rows.append({
                    "dataset_id": DATASETS["tracks" if kind == "track" else "cones"], "record_id": feature_id,
                    "source_id": storm["source_id"], "advisory_number": advisory,
                    "geometry": geometry, "observed_at_utc": storm["advisory_issued_at_utc"], "source": feed["source"],
                })
        batches = {"storms": status_rows, "points": point_rows, "tracks": track_rows, "cones": cone_rows}
        result: dict[str, Any] = {"fetched_storms": len(feed["storms"]), "fetched_points": len(point_rows), "fetched_tracks": len(track_rows), "fetched_cones": len(cone_rows), "fetched_at_utc": feed["fetched_at_utc"], "record_ids": {}}
        for kind, rows in batches.items():
            inserted = updated = 0
            ids = []
            for row in rows:
                record_id, action = self._write(self.store, row)
                ids.append(record_id)
                if action == "inserted":
                    inserted += 1
                else:
                    updated += 1
            result[kind] = {"dataset_id": DATASETS[kind], "inserted": inserted, "updated": updated, "record_count": len(rows)}
            result["record_ids"][kind] = ids
        self.store.save(self.SNAPSHOT_ID, {
            "fetched_at_utc": feed["fetched_at_utc"],
            "storms": [{"source_id": storm["source_id"], "advisory_number": storm["advisory_number"]} for storm in feed["storms"]],
        })
        return result

    def get(self, record_id: str) -> dict[str, Any] | None:
        return self.store.load(record_id)

    def list(self, dataset_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if dataset_id not in DATASETS.values():
            raise ValueError("Unknown cyclone dataset")
        rows = [row for row in self.store.list_all() if row.get("dataset_id") == dataset_id]
        snapshot = self.store.load(self.SNAPSHOT_ID)
        if snapshot:
            current = {(storm["source_id"], storm["advisory_number"]) for storm in snapshot.get("storms", [])}
            if dataset_id == DATASETS["storms"]:
                rows = [row for row in rows if row.get("fetched_at_utc") == snapshot.get("fetched_at_utc")]
            else:
                rows = [row for row in rows if (row.get("source_id"), row.get("advisory_number")) in current]
        rows.sort(key=lambda row: (row.get("observed_at_utc") or row.get("position_at_utc") or row.get("fetched_at_utc", ""), row.get("source_id", "")), reverse=True)
        return rows[offset:offset + limit]
