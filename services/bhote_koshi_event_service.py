"""Validation and persistence for the static Bhote Koshi event reconstruction."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import math
import re
from typing import Any

from services.artifact_store import ArtifactStore


class BhoteKoshiValidationError(ValueError):
    pass


class BhoteKoshiEventService:
    DATASET_ID = "gods_eye_view_bhote_koshi_flood"
    EVENT_DATASET_ID = "gods_eye_view_bhote_koshi_event"
    GEOMETRY_DATASET_ID = "gods_eye_view_bhote_koshi_geometries"
    MEDIA_DATASET_ID = "gods_eye_view_bhote_koshi_media_references"
    EVENT_ID = "bhote-koshi-2026"
    SOURCE_URL = "https://github.com/bilawalsidhu/gods-eye-view"

    def __init__(self, event_store: Any | None = None, geometry_store: Any | None = None,
                 media_store: Any | None = None, store_dir: str = "bhote_koshi_event") -> None:
        self.event_store = event_store or ArtifactStore(reports_dir=f"{store_dir}_events")
        self.geometry_store = geometry_store or ArtifactStore(reports_dir=f"{store_dir}_geometries")
        self.media_store = media_store or ArtifactStore(reports_dir=f"{store_dir}_media")

    @staticmethod
    def _valid_position(lon: Any, lat: Any) -> bool:
        return (
            not isinstance(lon, bool) and isinstance(lon, (int, float)) and math.isfinite(lon)
            and not isinstance(lat, bool) and isinstance(lat, (int, float)) and math.isfinite(lat)
            and -180 <= lon <= 180 and -90 <= lat <= 90
        )

    @classmethod
    def _valid_line(cls, coordinates: Any) -> bool:
        return isinstance(coordinates, list) and len(coordinates) >= 2 and all(
            isinstance(point, (list, tuple)) and len(point) >= 2
            and cls._valid_position(point[0], point[1]) for point in coordinates
        )

    @classmethod
    def _valid_record_id(cls, value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", value) is not None

    @staticmethod
    def _valid_optional_timestamp(value: Any) -> bool:
        if value is None:
            return True
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False

    @classmethod
    def validate_feed(cls, feed: Any) -> dict[str, Any]:
        if not isinstance(feed, dict) or feed.get("source") != "God's Eye View / GeoPera / Vantor Open Data":
            raise BhoteKoshiValidationError("Expected the God's Eye View Bhote Koshi source")
        event = feed.get("event")
        if not isinstance(event, dict) or event.get("id") != cls.EVENT_ID:
            raise BhoteKoshiValidationError("event pack must identify bhote-koshi-2026")
        if not isinstance(event.get("title"), str) or not event["title"].strip():
            raise BhoteKoshiValidationError("event title is required")
        observed_date = event.get("observedDate")
        try:
            if not isinstance(observed_date, str) or date.fromisoformat(observed_date).isoformat() != observed_date:
                raise ValueError
        except ValueError as exc:
            raise BhoteKoshiValidationError("observedDate must be a valid ISO date") from exc
        path = feed.get("flood_path_coordinates")
        if not cls._valid_line(path):
            raise BhoteKoshiValidationError("flood path must have at least two valid WGS84 positions")
        evidence = event.get("evidenceSpine")
        witnesses = event.get("witnessAnchors")
        if not isinstance(evidence, list) or not isinstance(witnesses, list):
            raise BhoteKoshiValidationError("event evidenceSpine and witnessAnchors must be arrays")
        corridor = event.get("reconstruction", {}).get("corridor")
        if not isinstance(corridor, list) or len(corridor) < 2:
            raise BhoteKoshiValidationError("reconstruction corridor must contain at least two vertices")
        if any(not isinstance(vertex, dict) or not cls._valid_position(vertex.get("lon"), vertex.get("lat")) for vertex in corridor):
            raise BhoteKoshiValidationError("reconstruction corridor contains invalid WGS84 coordinates")
        for key in ("before", "after"):
            imagery = event.get("imagery", {}).get(key)
            if imagery is not None:
                if not isinstance(imagery, dict) or not cls._valid_optional_timestamp(imagery.get("observedAt")):
                    raise BhoteKoshiValidationError(f"imagery.{key}.observedAt must be a valid source date")
        return deepcopy(feed)

    def ingest(self, feed: dict[str, Any]) -> dict[str, Any]:
        normalized = self.validate_feed(feed)
        event = normalized["event"]
        source_url = self.SOURCE_URL
        ingested_at = datetime.now(timezone.utc).isoformat()
        accepted_evidence: list[dict[str, Any]] = []
        accepted_witnesses: list[dict[str, Any]] = []
        accepted_media: list[dict[str, Any]] = []
        geometry_features: list[dict[str, Any]] = []
        rejected = {"event": 0, "geometry": 0, "media": 0}

        path = normalized["flood_path_coordinates"]
        geometry_features.append({
            "record_id": f"{self.EVENT_ID}__flood-path",
            "feature_kind": "simplified_flood_path",
            "source_file_role": "flood_path_module",
            "geometry": {"type": "LineString", "coordinates": path},
            "properties": {
                "description": "Simplified GeoPera river centerline from the debris-dammed lake toward Trishuli Bazaar.",
                "source_url": normalized.get("path_source_url"),
                "license": normalized.get("path_license"),
            },
        })

        corridor = event["reconstruction"]["corridor"]
        corridor_positions = [[vertex.get("lon"), vertex.get("lat")] for vertex in corridor]
        geometry_features.append({
            "record_id": f"{self.EVENT_ID}__reconstruction-corridor",
            "feature_kind": "schematic_reconstruction_corridor",
            "source_file_role": "event_pack.reconstruction.corridor",
            "geometry": {"type": "LineString", "coordinates": corridor_positions},
            "properties": {
                "vertex_metadata": deepcopy(corridor),
                "elapsed_seconds": event.get("reconstruction", {}).get("elapsedSeconds"),
                "label": event.get("reconstruction", {}).get("label"),
                "caveat": event.get("reconstruction", {}).get("caveat"),
            },
        })

        seen_ids: set[str] = set()
        seen_sequences: set[int] = set()
        for record in event["evidenceSpine"]:
            if not isinstance(record, dict):
                rejected["event"] += 1
                continue
            record_id, sequence = record.get("id"), record.get("sequence")
            timing = record.get("timing") or {}
            if (not isinstance(record, dict) or not self._valid_record_id(record_id)
                    or not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1
                    or sequence in seen_sequences or record_id in seen_ids
                    or not self._valid_position(record.get("lon"), record.get("lat"))
                    or not self._valid_optional_timestamp(timing.get("capturedAt"))):
                rejected["event"] += 1
                continue
            seen_ids.add(record_id)
            seen_sequences.add(sequence)
            accepted_evidence.append(deepcopy(record))
            geometry_features.append({
                "record_id": f"{self.EVENT_ID}__evidence__{record_id}",
                "feature_kind": "evidence_location",
                "source_file_role": "event_pack.evidenceSpine",
                "geometry": {"type": "Point", "coordinates": [record["lon"], record["lat"]]},
                "properties": deepcopy(record),
            })
            media = record.get("media")
            if isinstance(media, dict):
                source_media_url = media.get("sourceUrl")
                poster_url = media.get("posterUrl")
                if (not isinstance(source_media_url, str) or not source_media_url.startswith("https://")
                        or (poster_url is not None and (not isinstance(poster_url, str) or not poster_url.startswith("https://")))):
                    rejected["media"] += 1
                else:
                    accepted_media.append({
                        "record_id": f"{self.EVENT_ID}__media__{record_id}",
                        "evidence_id": record_id,
                        "sequence": sequence,
                        "title": record.get("title"),
                        "media": deepcopy(media),
                        "provenance": deepcopy(record.get("provenance")),
                        "source_url": source_url,
                        "media_mode": normalized.get("media_mode"),
                    })

        seen_witness_ids: set[str] = set()
        for witness in event["witnessAnchors"]:
            witness_id = witness.get("id") if isinstance(witness, dict) else None
            if (not self._valid_record_id(witness_id) or witness_id in seen_witness_ids
                    or not self._valid_position(witness.get("lon"), witness.get("lat"))):
                rejected["event"] += 1
                continue
            seen_witness_ids.add(witness_id)
            accepted_witnesses.append(deepcopy(witness))
            geometry_features.append({
                "record_id": f"{self.EVENT_ID}__witness__{witness_id}",
                "feature_kind": "witness_location",
                "source_file_role": "event_pack.witnessAnchors",
                "geometry": {"type": "Point", "coordinates": [witness["lon"], witness["lat"]]},
                "properties": deepcopy(witness),
            })

        stored_event = deepcopy(event)
        stored_event["evidenceSpine"] = accepted_evidence
        stored_event["witnessAnchors"] = accepted_witnesses
        source_provenance = {
            "provider": normalized["source"],
            "repository": source_url,
            "files": deepcopy(normalized["source_files"]),
            "attribution": normalized["attribution"],
            "path_source_url": normalized["path_source_url"],
            "path_license": normalized["path_license"],
            "media_mode": normalized["media_mode"],
            "data_mode": normalized["data_mode"],
            "presentation_metadata": normalized["presentation_metadata"],
        }
        event_record = {
            "record_id": self.EVENT_ID,
            "dataset_id": self.EVENT_DATASET_ID,
            "source_dataset_id": self.DATASET_ID,
            "event": stored_event,
            "source_provenance": source_provenance,
            "ingested_at_utc": ingested_at,
        }

        inserted = {"events": 0, "geometries": 0, "media": 0}
        updated = {"events": 0, "geometries": 0, "media": 0}
        self._save(self.event_store, self.EVENT_ID, event_record, "events", inserted, updated)
        for feature in geometry_features:
            record = {
                **feature,
                "dataset_id": self.GEOMETRY_DATASET_ID,
                "source_dataset_id": self.DATASET_ID,
                "event_id": self.EVENT_ID,
                "source_provenance": source_provenance,
                "ingested_at_utc": ingested_at,
            }
            self._save(self.geometry_store, feature["record_id"], record, "geometries", inserted, updated)
        for media in accepted_media:
            media.update({"dataset_id": self.MEDIA_DATASET_ID, "source_dataset_id": self.DATASET_ID,
                          "event_id": self.EVENT_ID, "source_provenance": source_provenance,
                          "ingested_at_utc": ingested_at})
            self._save(self.media_store, media["record_id"], media, "media", inserted, updated)

        valid_counts = {"events": 1, "geometries": len(geometry_features), "media": len(accepted_media)}
        return {
            "dataset_id": self.DATASET_ID,
            "data_mode": normalized["data_mode"],
            "status": "STATIC_PARTIAL" if sum(rejected.values()) else "STATIC_VERIFIED_PENDING_READBACK",
            "source_event_count": 1,
            "source_path_vertex_count": len(path),
            "source_evidence_count": len(event["evidenceSpine"]),
            "source_witness_count": len(event["witnessAnchors"]),
            "source_media_reference_count": sum(isinstance(row.get("media"), dict) for row in event["evidenceSpine"]),
            "valid_counts": valid_counts,
            "rejected_counts": rejected,
            "valid_record_count": sum(valid_counts.values()),
            "rejected_record_count": sum(rejected.values()),
            "inserted": inserted,
            "updated": updated,
            "source_provenance": source_provenance,
        }

    @staticmethod
    def _save(store: Any, key: str, record: dict[str, Any], category: str,
              inserted: dict[str, int], updated: dict[str, int]) -> None:
        action = "inserted" if store.load(key) is None else "updated"
        store.save(key, record)
        (inserted if action == "inserted" else updated)[category] += 1

    def get_event(self) -> dict[str, Any] | None:
        return self.event_store.load(self.EVENT_ID)

    def list_features(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        rows = self.geometry_store.list_all()
        rows.sort(key=lambda row: (row.get("feature_kind", ""), row.get("record_id", "")))
        selected = rows[offset:offset + limit]
        return {
            "type": "FeatureCollection", "dataset_id": self.GEOMETRY_DATASET_ID,
            "source_dataset_id": self.DATASET_ID, "count": len(selected),
            "total": len(rows), "limit": limit, "offset": offset,
            "features": [{
                "type": "Feature", "id": row["record_id"],
                "geometry": row["geometry"],
                "properties": {key: value for key, value in row.items()
                               if key not in ("geometry", "dataset_id", "source_dataset_id", "source_provenance", "ingested_at_utc")},
            } for row in selected],
        }

    def list_media(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        rows = self.media_store.list_all()
        rows.sort(key=lambda row: (row.get("sequence", 0), row.get("record_id", "")))
        return rows[offset:offset + limit]
