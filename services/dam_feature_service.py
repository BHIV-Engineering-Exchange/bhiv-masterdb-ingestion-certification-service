"""Validation and persistence for static GeoJSON dam features."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import re
from typing import Any

from services.artifact_store import ArtifactStore


class DamFeatureValidationError(ValueError):
    pass


class DamFeatureService:
    DATASET_ID = "gods_eye_view_dams"
    ATTRIBUTE_DATASET_ID = "gods_eye_view_dam_attributes"
    GEOMETRY_DATASET_ID = "gods_eye_view_dam_geometries"
    SOURCE_URL = "https://github.com/bilawalsidhu/gods-eye-view/blob/main/src/data/local_data/dams/dams.geojsonl"
    GEOMETRY_TYPES = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}

    def __init__(self, attribute_store: Any | None = None, geometry_store: Any | None = None,
                 store_dir: str = "dam_features") -> None:
        self.attribute_store = attribute_store or ArtifactStore(reports_dir=f"{store_dir}_attributes")
        self.geometry_store = geometry_store or ArtifactStore(reports_dir=f"{store_dir}_geometries")

    @staticmethod
    def _coordinates(geometry: dict[str, Any]):
        kind, coords = geometry.get("type"), geometry.get("coordinates")
        if kind == "Point":
            yield coords
        elif kind in ("MultiPoint", "LineString") and isinstance(coords, list):
            yield from coords
        elif kind in ("MultiLineString", "Polygon") and isinstance(coords, list):
            for part in coords:
                if isinstance(part, list):
                    yield from part
        elif kind == "MultiPolygon" and isinstance(coords, list):
            for polygon in coords:
                if isinstance(polygon, list):
                    for ring in polygon:
                        if isinstance(ring, list):
                            yield from ring

    @classmethod
    def validate_feature(cls, feature: Any) -> dict[str, Any]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise DamFeatureValidationError("record must be a GeoJSON Feature")
        source_id = feature.get("id")
        props = feature.get("properties")
        geometry = feature.get("geometry")
        if source_id is None or isinstance(source_id, (dict, list, bool)):
            raise DamFeatureValidationError("feature id must be a scalar source identifier")
        if not isinstance(props, dict):
            raise DamFeatureValidationError("properties must be an object")
        osm_id = props.get("osm_id")
        source_layer = props.get("source_layer")
        if osm_id is None or isinstance(osm_id, (dict, list, bool)):
            raise DamFeatureValidationError("properties.osm_id must be a scalar source identifier")
        if not isinstance(source_layer, str) or not source_layer.strip():
            raise DamFeatureValidationError("properties.source_layer is required")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", source_layer) is None:
            raise DamFeatureValidationError("properties.source_layer contains unsupported identifier characters")
        tags = props.get("tags")
        if tags is not None and not isinstance(tags, dict):
            raise DamFeatureValidationError("properties.tags must be an object when present")
        if not isinstance(geometry, dict) or geometry.get("type") not in cls.GEOMETRY_TYPES:
            raise DamFeatureValidationError("geometry must use a supported GeoJSON geometry type")
        points = list(cls._coordinates(geometry))
        if not points:
            raise DamFeatureValidationError("geometry must contain coordinates")
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise DamFeatureValidationError("each position must contain longitude and latitude")
            lon, lat = point[:2]
            if (isinstance(lon, bool) or not isinstance(lon, (int, float)) or not math.isfinite(lon)
                    or isinstance(lat, bool) or not isinstance(lat, (int, float)) or not math.isfinite(lat)):
                raise DamFeatureValidationError("coordinates must be finite numbers")
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise DamFeatureValidationError("coordinates must be within WGS84 bounds")
        if geometry["type"] in ("Polygon", "MultiPolygon"):
            polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
            if not isinstance(polygons, list):
                raise DamFeatureValidationError("polygon coordinates must be an array")
            for polygon in polygons:
                if not isinstance(polygon, list) or not polygon:
                    raise DamFeatureValidationError("polygon must include an exterior ring")
                for ring in polygon:
                    if (not isinstance(ring, list) or len(ring) < 4 or
                            ring[0][:2] != ring[-1][:2]):
                        raise DamFeatureValidationError("polygon rings must have at least four closed positions")

        # OSM objects can legitimately have multiple geometry representations.
        # source_layer makes the source identity stable without discarding one.
        source_key = f"{osm_id}__{source_layer}"
        return {
            "source_key": source_key,
            "source_id": source_id,
            "osm_id": osm_id,
            "source_layer": source_layer,
            "properties": deepcopy(props),
            "geometry": deepcopy(geometry),
        }

    def ingest(self, feed: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(feed, dict) or feed.get("source") != "God's Eye View / OpenInfraMap":
            raise DamFeatureValidationError("Expected the God's Eye View dams source")
        features = feed.get("features")
        if not isinstance(features, list):
            raise DamFeatureValidationError("features must be a list")

        valid: list[dict[str, Any]] = []
        rejected = int(feed.get("parse_errors", 0) or 0)
        rejection_reasons: dict[str, int] = {}
        seen: set[str] = set()
        for raw in features:
            try:
                record = self.validate_feature(raw)
                if record["source_key"] in seen:
                    raise DamFeatureValidationError("duplicate source identifier and source layer")
                seen.add(record["source_key"])
                valid.append(record)
            except (DamFeatureValidationError, TypeError, ValueError) as exc:
                rejected += 1
                reason = str(exc) or "invalid feature"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

        # Persist each source feature as an attributes record and a separate
        # GeoJSON geometry record, sharing one deterministic source key.
        inserted = updated = 0
        ingested_at = datetime.now(timezone.utc).isoformat()
        for feature in valid:
            key = feature["source_key"]
            previous = self.attribute_store.load(key)
            action = "inserted" if previous is None else "updated"
            attributes = {
                "record_id": key,
                "dataset_id": self.ATTRIBUTE_DATASET_ID,
                "source_dataset_id": self.DATASET_ID,
                "source_id": feature["source_id"],
                "osm_id": feature["osm_id"],
                "source_layer": feature["source_layer"],
                "properties": feature["properties"],
                "source_url": self.SOURCE_URL,
                "license": feed.get("license"),
                "attribution": feed.get("attribution"),
                "ingested_at_utc": ingested_at,
            }
            geometry = {
                "record_id": key,
                "dataset_id": self.GEOMETRY_DATASET_ID,
                "source_dataset_id": self.DATASET_ID,
                "source_id": feature["source_id"],
                "osm_id": feature["osm_id"],
                "source_layer": feature["source_layer"],
                "geometry": feature["geometry"],
                "source_url": self.SOURCE_URL,
                "ingested_at_utc": ingested_at,
            }
            self.attribute_store.save(key, attributes)
            self.geometry_store.save(key, geometry)
            if action == "inserted":
                inserted += 1
            else:
                updated += 1
        return {
            "dataset_id": self.DATASET_ID,
            "source_feature_count": feed.get("source_feature_count", len(features) + int(feed.get("parse_errors", 0) or 0)),
            "fetched": len(features),
            "valid": len(valid),
            "rejected": rejected,
            "rejection_reasons": rejection_reasons,
            "inserted": inserted,
            "updated": updated,
            "attribute_records": len(self.attribute_store.list_all()),
            "geometry_records": len(self.geometry_store.list_all()),
            "data_mode": "STATIC_SNAPSHOT",
        }

    def list_attributes(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        records = self.attribute_store.list_all()
        records.sort(key=lambda r: (str(r.get("properties", {}).get("name") or "").casefold(), str(r.get("record_id", ""))))
        return records[offset:offset + limit]

    def list_features(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        records = self.geometry_store.list_all()
        records.sort(key=lambda r: str(r.get("record_id", "")))
        selected = records[offset:offset + limit]
        return {
            "type": "FeatureCollection",
            "dataset_id": self.DATASET_ID,
            "count": len(selected),
            "total": len(records),
            "limit": limit,
            "offset": offset,
            "features": [
                {"type": "Feature", "id": r["record_id"], "properties": {
                    "record_id": r["record_id"], "source_id": r["source_id"],
                    "osm_id": r["osm_id"], "source_layer": r["source_layer"]
                }, "geometry": r["geometry"]}
                for r in selected
            ],
        }
