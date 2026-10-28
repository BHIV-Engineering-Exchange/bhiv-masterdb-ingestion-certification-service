"""Validation and separate attribute/geometry storage for Natural Earth sets."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any

from services.artifact_store import ArtifactStore


class NaturalEarthValidationError(ValueError):
    pass


class NaturalEarthFeatureService:
    DATASETS = {
        "regions": {
            "dataset_id": "gods_eye_view_natural_earth_regions",
            "attributes_dataset_id": "gods_eye_view_natural_earth_regions_attributes",
            "geometry_dataset_id": "gods_eye_view_natural_earth_regions_geometries",
            "source_name": "Natural Earth 10m physical vectors — ne_10m_geography_regions_polys",
        },
        "marine": {
            "dataset_id": "gods_eye_view_natural_earth_marine",
            "attributes_dataset_id": "gods_eye_view_natural_earth_marine_attributes",
            "geometry_dataset_id": "gods_eye_view_natural_earth_marine_geometries",
            "source_name": "Natural Earth 10m physical vectors — ne_10m_geography_marine_polys",
        },
    }
    ATTRIBUTION = "Natural Earth (naturalearthdata.com); public domain."
    LICENSE = "Public domain (Natural Earth — naturalearthdata.com)"

    def __init__(self, store_dir: str = "natural_earth_store") -> None:
        self.store_dir = store_dir
        self._stores: dict[str, tuple[ArtifactStore, ArtifactStore]] = {}
        for key, config in self.DATASETS.items():
            self._stores[key] = (
                ArtifactStore(reports_dir=f"{store_dir}/{key}_attributes"),
                ArtifactStore(reports_dir=f"{store_dir}/{key}_geometries"),
            )

    @classmethod
    def validate_feed(cls, dataset: str, feed: Any) -> dict[str, Any]:
        config = cls.DATASETS.get(dataset)
        if config is None:
            raise NaturalEarthValidationError("Unknown Natural Earth dataset")
        if not isinstance(feed, dict) or not isinstance(feed.get("meta"), dict):
            raise NaturalEarthValidationError("Natural Earth root must contain source metadata")
        meta = feed["meta"]
        if meta.get("source") != config["source_name"]:
            raise NaturalEarthValidationError("Natural Earth source metadata does not match dataset")
        features = feed.get("features")
        if not isinstance(features, list):
            raise NaturalEarthValidationError("Natural Earth features must be an array")
        declared_count = meta.get("featureCount")
        if isinstance(declared_count, bool) or not isinstance(declared_count, int) or declared_count != len(features):
            raise NaturalEarthValidationError("Natural Earth metadata featureCount does not match source array")
        if meta.get("license") != cls.LICENSE:
            raise NaturalEarthValidationError("Natural Earth license metadata is missing or changed")
        return {"meta": deepcopy(meta), "features": deepcopy(features), "source_feature_count": len(features)}

    @staticmethod
    def _position_valid(position: Any) -> bool:
        if not isinstance(position, (list, tuple)) or len(position) != 2:
            return False
        lon, lat = position
        return (
            not isinstance(lon, bool) and isinstance(lon, (int, float)) and math.isfinite(lon)
            and not isinstance(lat, bool) and isinstance(lat, (int, float)) and math.isfinite(lat)
            and -180 <= lon <= 180 and -90 <= lat <= 90
        )

    @classmethod
    def validate_feature(cls, feature: Any) -> dict[str, Any]:
        if not isinstance(feature, dict):
            raise NaturalEarthValidationError("feature must be an object")
        if not isinstance(feature.get("name"), str) or not feature["name"].strip():
            raise NaturalEarthValidationError("feature name is required")
        if not isinstance(feature.get("featurecla"), str) or not feature["featurecla"].strip():
            raise NaturalEarthValidationError("featurecla is required")
        if "namealt" in feature and not isinstance(feature["namealt"], str):
            raise NaturalEarthValidationError("namealt must be a string when present")
        source_polygons = feature.get("polygons")
        if not isinstance(source_polygons, list) or not source_polygons:
            raise NaturalEarthValidationError("polygons must contain at least one outer ring")

        normalized_rings: list[list[list[float]]] = []
        closed_rings_added = 0
        for ring in source_polygons:
            if not isinstance(ring, list) or len(ring) < 3:
                raise NaturalEarthValidationError("each polygon ring must have at least three positions")
            if any(not cls._position_valid(position) for position in ring):
                raise NaturalEarthValidationError("polygon positions must be finite WGS84 longitude/latitude pairs")
            if len({(position[0], position[1]) for position in ring}) < 3:
                raise NaturalEarthValidationError("polygon ring must have at least three distinct positions")
            normalized = deepcopy(ring)
            if normalized[0] != normalized[-1]:
                normalized.append(deepcopy(normalized[0]))
                closed_rings_added += 1
            normalized_rings.append(normalized)

        if len(normalized_rings) == 1:
            geometry = {"type": "Polygon", "coordinates": [normalized_rings[0]]}
        else:
            geometry = {"type": "MultiPolygon", "coordinates": [[ring] for ring in normalized_rings]}
        # Natural Earth source features have no source id. Keep every original
        # non-geometry field intact and use source order for a separate storage key.
        attributes = {key: deepcopy(value) for key, value in feature.items() if key != "polygons"}
        return {"attributes": attributes, "geometry": geometry, "closed_rings_added": closed_rings_added}

    def ingest(self, dataset: str, source: dict[str, Any]) -> dict[str, Any]:
        config = self.DATASETS.get(dataset)
        if config is None:
            raise NaturalEarthValidationError("Unknown Natural Earth dataset")
        validated_feed = self.validate_feed(dataset, source.get("feed"))
        attributes_store, geometry_store = self._stores[dataset]
        valid: list[dict[str, Any]] = []
        rejected_reasons: dict[str, int] = {}
        rings_closed = 0
        for index, feature in enumerate(validated_feed["features"]):
            try:
                record = self.validate_feature(feature)
                record["source_feature_index"] = index
                record["record_id"] = f"{dataset}_{index:06d}"
                rings_closed += record["closed_rings_added"]
                valid.append(record)
            except NaturalEarthValidationError as exc:
                reason = str(exc)
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1

        source_count = validated_feed["source_feature_count"]
        base = {
            "dataset_id": config["dataset_id"],
            "source_feature_count": source_count,
            "fetched": len(validated_feed["features"]),
            "valid": len(valid),
            "rejected": source_count - len(valid),
            "rejection_reasons": rejected_reasons,
            "closed_rings_added_for_geojson": rings_closed,
            "data_mode": "STATIC_SNAPSHOT",
        }
        # Keep the last good snapshot intact unless the entire new source is valid.
        if len(valid) != source_count:
            base.update({
                "status": "STATIC_PARTIAL",
                "attribute_records": len(attributes_store.list_all()),
                "geometry_records": len(geometry_store.list_all()),
            })
            return base

        now = datetime.now(timezone.utc).isoformat()
        metadata = {
            "source_file": source.get("source_file"),
            "source_relative_path": source.get("source_relative_path"),
            "source_repository": source.get("source_repository"),
            "source_sha256": source.get("source_sha256"),
            "source_meta": validated_feed["meta"],
            "attribution": self.ATTRIBUTION,
            "license": self.LICENSE,
        }
        new_keys = {record["record_id"] for record in valid}
        for record in valid:
            record_id = record["record_id"]
            source_index = record["source_feature_index"]
            attr_record = {
                "record_id": record_id,
                "dataset_id": config["attributes_dataset_id"],
                "source_dataset_id": config["dataset_id"],
                "source_feature_index": source_index,
                "attributes": record["attributes"],
                **metadata,
                "ingested_at_utc": now,
            }
            geom_record = {
                "record_id": record_id,
                "dataset_id": config["geometry_dataset_id"],
                "source_dataset_id": config["dataset_id"],
                "source_feature_index": source_index,
                "geometry": record["geometry"],
                **metadata,
                "ingested_at_utc": now,
            }
            attributes_store.save(record_id, attr_record)
            geometry_store.save(record_id, geom_record)
        for store in (attributes_store, geometry_store):
            for record in store.list_all():
                record_id = record.get("record_id")
                if isinstance(record_id, str) and record_id.startswith(f"{dataset}_") and record_id not in new_keys:
                    store.delete(record_id)

        attr_count = len(attributes_store.list_all())
        geom_count = len(geometry_store.list_all())
        base.update({
            "status": "VALIDATED_PENDING_READBACK",
            "inserted": source_count,
            "updated": 0,
            "attribute_records": attr_count,
            "geometry_records": geom_count,
            "expected_geometry_types": dict(self.geometry_type_counts(valid)),
            "source_sha256": source.get("source_sha256"),
        })
        return base

    @staticmethod
    def geometry_type_counts(validated_records: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in validated_records:
            kind = record["geometry"]["type"]
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def read_attributes(self, dataset: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        config = self.DATASETS[dataset]
        rows = sorted(self._stores[dataset][0].list_all(), key=lambda row: row.get("source_feature_index", -1))
        selected = rows[offset:offset + limit]
        return {
            "dataset_id": config["dataset_id"], "attribute_dataset_id": config["attributes_dataset_id"],
            "count": len(selected), "total": len(rows), "limit": limit, "offset": offset,
            "features": selected,
        }

    def read_features(self, dataset: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        config = self.DATASETS[dataset]
        attrs_store, geometry_store = self._stores[dataset]
        attrs = {row["record_id"]: row for row in attrs_store.list_all()}
        geometries = sorted(geometry_store.list_all(), key=lambda row: row.get("source_feature_index", -1))
        selected = geometries[offset:offset + limit]
        features = []
        for geometry_record in selected:
            properties = attrs.get(geometry_record["record_id"], {}).get("attributes", {})
            features.append({
                "type": "Feature",
                "id": geometry_record["record_id"],
                "properties": deepcopy(properties),
                "geometry": geometry_record["geometry"],
            })
        return {
            "type": "FeatureCollection", "dataset_id": config["dataset_id"],
            "count": len(features), "total": len(geometries), "limit": limit, "offset": offset,
            "features": features,
        }

    def readback_counts(self, dataset: str) -> dict[str, int]:
        attrs_store, geometry_store = self._stores[dataset]
        return {"attributes": len(attrs_store.list_all()), "geometries": len(geometry_store.list_all())}
