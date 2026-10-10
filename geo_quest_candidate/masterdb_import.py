"""Strict intake of the God’s Eye View evidence packet into candidate storage."""
import hashlib
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from geo_quest_candidate.service import (
    CandidateArtifactStore,
    CandidateNotFoundError,
    CandidateRegistrationError,
)
from services.capability_registry_service import CapabilityNotFoundError
from services.mdu_client import MDUUnavailableError
from services.package_registry_service import PackageNotFoundError

logger = logging.getLogger("masterdb")

PACKET_ID = "gev-geospatial-masterdb-intake"
PACKET_VERSION = 1
REQUIRED_RECORD_FIELDS = {
    "capabilityId",
    "capabilityName",
    "classification",
    "purpose",
    "source",
    "datasets",
    "authorityCustodian",
    "input",
    "output",
    "dependencies",
    "spatialCoverage",
    "temporalCoverage",
    "schema",
    "apiInterface",
    "license",
    "attribution",
    "provenance",
    "validationStatus",
    "qualityStatus",
    "knownLimitations",
    "potentialConsumers",
    "bharatMalaRelevance",
    "vanaFinRelevance",
    "masterdbRegistrationStatus",
    "nextRequiredAction",
    "evidenceLocation",
}
_NON_SOURCE_WORDS = {
    "data", "dataset", "source", "provider", "api", "with", "from", "via",
    "derived", "layers", "layer", "snapshot", "the", "and", "local",
}
_LICENSE_FAMILIES = (
    ("CC BY-NC-SA 3.0", ("cc by nc sa 3.0", "cc by-nc-sa 3.0")),
    ("CC BY-NC 4.0", ("cc by-nc 4.0", "cc by nc 4.0")),
    ("ODbL 1.0", ("odbl 1.0", "odbl-1.0", "open database license")),
    ("CC BY 4.0", ("cc by 4.0", "cc-by 4.0")),
    ("Public domain", ("public domain",)),
    ("Provider terms", ("provider/api terms", "provider terms")),
)


class CapabilityLookup(Protocol):
    def get_capability(self, capability_id: str) -> Any: ...


class DatasetLookup(Protocol):
    def get_by_dataset_id(self, dataset_id: str) -> Any: ...


class MDUContractLookup(Protocol):
    def is_live(self) -> bool: ...

    def fetch_schema_contract(self, dataset_id: str) -> Dict[str, Any]: ...


class CandidatePackageRetrieveRequest(BaseModel):
    dataset_id: str = Field(min_length=1)
    purpose: str = Field(default="registry_review", min_length=1)


class CandidateUseDeniedError(PermissionError):
    """Raised when candidate data is requested for an unapproved use."""


class GeospatialExportCandidateService:
    """Validates a GEV export and stages it in the existing candidate store."""

    def __init__(
        self,
        store: CandidateArtifactStore,
        import_dir: Optional[Path] = None,
        capability_registry: Optional[CapabilityLookup] = None,
        dataset_registry: Optional[DatasetLookup] = None,
        mdu_contracts: Optional[MDUContractLookup] = None,
    ) -> None:
        configured_dir = os.environ.get("GEV_MASTERDB_IMPORT_DIR")
        sibling_gev = Path(__file__).resolve().parents[2] / "gods-eye-view"
        self.import_dir = Path(import_dir or configured_dir or sibling_gev / "evidence_packet" / "masterdb_import")
        self.store = store
        self.capability_registry = capability_registry
        self.dataset_registry = dataset_registry
        self.mdu_contracts = mdu_contracts

    def register_candidate(self, actor: str) -> Dict[str, Any]:
        candidate = self._load_and_validate_export()
        self._check_registry_conflicts(candidate["manifest"], candidate["records"])
        mdu_status = self._check_mdu_contracts(candidate["manifest"], candidate["records"])

        existing = self.store.load(PACKET_ID)
        if existing is not None:
            self._validate_stored_candidate(existing)
            existing_source_hash = existing.get("source_package_sha256") or self._source_package_sha256(
                existing["manifest"],
                existing["registry_records"],
                existing["dataset_records_sidecar"],
                existing["artifact_sha256"],
            )
            if existing_source_hash != candidate["source_package_sha256"]:
                raise CandidateRegistrationError(
                    "The GEV export differs from the already staged packet; refusing to overwrite the candidate."
                )
            return self._summary(existing)

        bundle = {
            "candidate_package_id": PACKET_ID,
            "packet_version": PACKET_VERSION,
            "registration_status": "PENDING_AUTHORIZATION",
            "canonical": False,
            "discoverable": False,
            "registered_by": actor,
            "manifest": candidate["manifest"],
            "registry_records": candidate["records"],
            "dataset_records_sidecar": candidate["sidecar"],
            "mdu_contract_validation": mdu_status,
            "artifacts": candidate["artifacts"],
            "artifact_sha256": candidate["artifact_sha256"],
            "source_package_sha256": candidate["source_package_sha256"],
        }
        bundle["bundle_sha256"] = self._bundle_sha256(bundle)
        self.store.save(PACKET_ID, bundle)
        logger.info(
            "gev_geospatial_candidate_staged packet_id=%s actor=%s artifacts=%s mdu_status=%s",
            PACKET_ID,
            actor,
            len(bundle["artifacts"]),
            mdu_status["status"],
        )
        return self._summary(bundle)

    def get_candidate(self) -> Dict[str, Any]:
        bundle = self.store.load(PACKET_ID)
        if bundle is None:
            raise CandidateNotFoundError(f"Candidate package '{PACKET_ID}' is not registered.")
        self._validate_stored_candidate(bundle)
        return {
            **self._summary(bundle),
            "manifest": bundle["manifest"],
            "registry_records": bundle["registry_records"],
            "mdu_contract_validation": bundle["mdu_contract_validation"],
        }

    def retrieve(self, request: CandidatePackageRetrieveRequest) -> Dict[str, Any]:
        if request.purpose.strip().casefold() != "registry_review":
            raise CandidateUseDeniedError(
                "Candidate-only data can be retrieved only for registry_review; production and commercial use require approval."
            )
        bundle = self.store.load(PACKET_ID)
        if bundle is None:
            raise CandidateNotFoundError(f"Candidate package '{PACKET_ID}' is not registered.")
        self._validate_stored_candidate(bundle)
        manifest_entry = next(
            (item for item in bundle["manifest"]["datasets"] if item["datasetId"] == request.dataset_id),
            None,
        )
        if manifest_entry is None:
            raise CandidateNotFoundError(f"Dataset candidate '{request.dataset_id}' is not in the staged package.")
        artifact = bundle["artifacts"][manifest_entry["file"]]
        payload = json.loads(artifact["content"])
        record = next(
            item for item in bundle["registry_records"]
            if item["capabilityId"] == manifest_entry["registryRecordId"]
        )
        return {
            "candidate_package_id": PACKET_ID,
            "dataset_id": request.dataset_id,
            "external_record_id": manifest_entry["registryRecordId"],
            "registration_status": bundle["registration_status"],
            "canonical": False,
            "discoverable": False,
            "purpose": request.purpose,
            "license": record["license"],
            "attribution": record["attribution"],
            "known_limitations": record["knownLimitations"],
            "artifact_sha256": artifact["sha256"],
            "data": payload,
        }

    def _load_and_validate_export(self) -> Dict[str, Any]:
        manifest = self._read_json(self.import_dir / "manifest.json")
        records_doc = self._read_json(self.import_dir / "registry_records.json")
        sidecar_doc = self._read_json(self.import_dir / "data" / "dataset_records.json")
        datasets = manifest.get("datasets")
        records = records_doc.get("records")
        sidecar = sidecar_doc.get("records")
        if (
            manifest.get("packetId") != PACKET_ID
            or manifest.get("packetVersion") != PACKET_VERSION
            or not isinstance(datasets, list)
            or not datasets
            or not isinstance(records, list)
            or not isinstance(sidecar, list)
        ):
            raise CandidateRegistrationError("GEV manifest or registry envelope is invalid.")
        if records != sidecar:
            raise CandidateRegistrationError("GEV registry_records.json and data/dataset_records.json disagree.")
        if len(datasets) != len(records):
            raise CandidateRegistrationError("GEV manifest and registry record counts disagree.")

        record_by_id = {}
        for record in records:
            if not isinstance(record, dict):
                raise CandidateRegistrationError("Every GEV registry record must be a JSON object.")
            missing = REQUIRED_RECORD_FIELDS - set(record)
            if missing:
                raise CandidateRegistrationError(
                    f"GEV record is missing required fields: {', '.join(sorted(missing))}."
                )
            if (
                not isinstance(record.get("datasets"), list)
                or not isinstance(record.get("schema"), dict)
                or not isinstance(record.get("classification"), dict)
            ):
                raise CandidateRegistrationError("GEV record datasets, schema, and classification have invalid types.")
            if any(not isinstance(dataset, dict) for dataset in record["datasets"]):
                raise CandidateRegistrationError("GEV record dataset entries must be JSON objects.")
            record_id = record["capabilityId"]
            if not isinstance(record_id, str) or not record_id.strip() or record_id in record_by_id:
                raise CandidateRegistrationError("GEV candidate record IDs must be non-empty and unique.")
            record_by_id[record_id] = record

        artifact_paths = set()
        dataset_ids = set()
        artifacts: Dict[str, Dict[str, str]] = {}
        artifact_sha256: Dict[str, str] = {}
        for entry in datasets:
            if not isinstance(entry, dict):
                raise CandidateRegistrationError("GEV manifest dataset entries must be JSON objects.")
            dataset_id = entry.get("datasetId")
            record_id = entry.get("registryRecordId")
            relative = entry.get("file")
            if (
                not isinstance(dataset_id, str)
                or not dataset_id
                or dataset_id in dataset_ids
                or not isinstance(record_id, str)
                or record_id not in record_by_id
                or not isinstance(relative, str)
                or not relative.startswith("data/")
                or relative in artifact_paths
            ):
                raise CandidateRegistrationError("GEV manifest contains a duplicate or invalid dataset reference.")
            if any(
                entry.get(field) is not None and not isinstance(entry.get(field), str)
                for field in ("source", "sourceUrl", "sourceCommit", "attribution", "format")
            ):
                raise CandidateRegistrationError(
                    f"GEV manifest metadata contains an invalid string field for '{dataset_id}'."
                )
            dataset_ids.add(dataset_id)
            artifact_paths.add(relative)
            record = record_by_id[record_id]
            record_datasets = record.get("datasets")
            if (
                not isinstance(record_datasets, list)
                or len(record_datasets) != 1
                or record_datasets[0].get("file") != relative
            ):
                raise CandidateRegistrationError(
                    f"GEV record '{record_id}' does not reference manifest artifact '{relative}'."
                )
            raw, payload = self._read_artifact(relative)
            self._validate_artifact(entry, record, payload, raw)
            digest = hashlib.sha256(raw).hexdigest()
            artifacts[relative] = {
                "content": raw.decode("utf-8"),
                "sha256": digest,
            }
            artifact_sha256[relative] = digest

        on_disk_data = {
            f"data/{item.name}"
            for item in (self.import_dir / "data").iterdir()
            if item.is_file() and item.name != "dataset_records.json"
        }
        if on_disk_data != artifact_paths:
            raise CandidateRegistrationError(
                "GEV manifest artifact inventory does not exactly match files in data/."
            )
        if {record["capabilityId"] for record in records} != {
            entry["registryRecordId"] for entry in datasets
        }:
            raise CandidateRegistrationError("GEV registry contains records not referenced by the manifest.")

        return {
            "manifest": manifest,
            "records": records,
            "sidecar": sidecar,
            "artifacts": artifacts,
            "artifact_sha256": artifact_sha256,
            "source_package_sha256": self._source_package_sha256(
                manifest, records, sidecar, artifact_sha256
            ),
        }

    def _validate_artifact(
        self,
        entry: Dict[str, Any],
        record: Dict[str, Any],
        payload: Any,
        raw: bytes,
    ) -> None:
        if not isinstance(payload, (dict, list)):
            raise CandidateRegistrationError(f"GEV artifact '{entry['file']}' must be a JSON object or array.")
        record_dataset = record["datasets"][0]
        if self._format_family(record_dataset.get("format")) != self._format_family(entry.get("format")):
            raise CandidateRegistrationError(
                f"GEV manifest/record format mismatch for '{entry['datasetId']}'."
            )
        if self._license_family(entry.get("license")) != self._license_family(record.get("license")):
            raise CandidateRegistrationError(
                f"GEV manifest/record license mismatch for '{entry['datasetId']}'."
            )
        manifest_attribution = [
            token for token in self._normalize(entry.get("attribution") or "").split()
            if token != "the"
        ]
        record_attribution = [
            token for token in self._normalize(record.get("attribution") or "").split()
            if token != "the"
        ]
        if manifest_attribution and record_attribution[:len(manifest_attribution)] != manifest_attribution:
            raise CandidateRegistrationError(
                f"GEV manifest/record attribution mismatch for '{entry['datasetId']}'."
            )
        if entry.get("source"):
            source_tokens = self._meaningful_tokens(entry["source"])
            registry_tokens = self._meaningful_tokens(record.get("source", ""))
            classification_tokens = self._meaningful_tokens(record.get("classification", {}).get("source", ""))
            if not source_tokens.intersection(registry_tokens | classification_tokens):
                raise CandidateRegistrationError(
                    f"GEV manifest/record source provenance mismatch for '{entry['datasetId']}'."
                )
        if entry.get("sourceUrl") and entry["sourceUrl"].encode("utf-8") not in raw:
            raise CandidateRegistrationError(
                f"GEV artifact '{entry['file']}' does not contain the manifest source URL."
            )
        if entry.get("sourceCommit") and entry["sourceCommit"].split()[0].encode("utf-8") not in raw:
            raise CandidateRegistrationError(
                f"GEV artifact '{entry['file']}' does not contain the manifest source commit."
            )

        is_unavailable = entry["datasetId"] == "forest-data-gap"
        if is_unavailable:
            if (
                not isinstance(payload, dict)
                or entry.get("recordCount") != 0
                or payload.get("is_dataset") is not False
                or payload.get("feature_count") != 0
                or payload.get("features") != []
            ):
                raise CandidateRegistrationError("Forest status artifact must explicitly report no dataset/features.")
            if (
                record["schema"].get("is_dataset") is not False
                or record["schema"].get("feature_count") != 0
            ):
                raise CandidateRegistrationError("Forest gap record must not claim a geospatial schema.")
            return

        if entry.get("format") == "GeoJSON FeatureCollection":
            self._validate_geojson(entry, record, payload)
            return
        if entry.get("format") == "Open-Meteo JSON API response":
            self._validate_weather_snapshot(entry, record, payload)
            return
        raise CandidateRegistrationError(
            f"GEV artifact '{entry['file']}' has an unsupported declared format."
        )

    def _validate_geojson(self, entry: Dict[str, Any], record: Dict[str, Any], payload: Any) -> None:
        record_dataset = record["datasets"][0]
        if (
            not isinstance(payload, dict)
            or payload.get("type") != "FeatureCollection"
            or not isinstance(payload.get("features"), list)
            or payload["type"] != record["schema"].get("root")
            or len(payload["features"]) != entry.get("recordCount")
        ):
            raise CandidateRegistrationError(
                f"GeoJSON root or feature count does not match metadata for '{entry['datasetId']}'."
            )
        expected_feature_count = record["datasets"][0].get("featureCount")
        if expected_feature_count is not None and len(payload["features"]) != expected_feature_count:
            raise CandidateRegistrationError(
                f"GeoJSON feature count does not match registry record for '{entry['datasetId']}'."
            )
        feature_schema = record["schema"].get("feature", {})
        if not isinstance(feature_schema, dict):
            raise CandidateRegistrationError(
                f"Registry feature schema must be an object for '{entry['datasetId']}'."
            )
        if (
            feature_schema.get("type") not in (None, "Feature")
            or not isinstance(feature_schema.get("geometry"), (dict, str))
            or not isinstance(feature_schema.get("properties"), dict)
        ):
            raise CandidateRegistrationError(
                f"Registry schema does not describe GeoJSON Features for '{entry['datasetId']}'."
            )
        for index, feature in enumerate(payload["features"]):
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise CandidateRegistrationError(
                    f"GeoJSON feature {index} is invalid for '{entry['datasetId']}'."
                )
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict) or geometry.get("type") not in {
                "Point", "MultiPoint", "LineString", "MultiLineString",
                "Polygon", "MultiPolygon", "GeometryCollection",
            }:
                raise CandidateRegistrationError(
                    f"GeoJSON feature {index} has an unsupported geometry."
                )
            if geometry.get("type") == "GeometryCollection":
                raise CandidateRegistrationError("GeometryCollection validation is not implemented for this packet.")
            if not self._coordinates_valid(geometry.get("coordinates")):
                raise CandidateRegistrationError(
                    f"GeoJSON feature {index} has invalid WGS84 coordinates."
                )
            self._validate_declared_feature_schema(entry, feature_schema, feature, geometry)
            embedded_license = feature.get("properties", {}).get("license")
            if embedded_license and self._license_family(embedded_license) != self._license_family(entry.get("license")):
                raise CandidateRegistrationError(
                    f"GeoJSON feature license conflicts with manifest for '{entry['datasetId']}'."
                )
            expected_coordinates = entry.get("coordinateCount")
            declared_coordinates = record_dataset.get("coordinateCount")
            if expected_coordinates is not None:
                coordinates = geometry.get("coordinates")
                if (
                    geometry.get("type") != "LineString"
                    or not isinstance(coordinates, list)
                    or len(coordinates) != expected_coordinates
                    or declared_coordinates != expected_coordinates
                ):
                    raise CandidateRegistrationError(
                        f"GeoJSON coordinate count does not match metadata for '{entry['datasetId']}'."
                    )

    def _validate_declared_feature_schema(
        self,
        entry: Dict[str, Any],
        schema: Dict[str, Any],
        feature: Dict[str, Any],
        geometry: Dict[str, Any],
    ) -> None:
        declared_geometry = schema.get("geometry")
        if isinstance(declared_geometry, dict):
            allowed_geometry = {declared_geometry.get("type")}
        elif isinstance(declared_geometry, str):
            allowed_geometry = set(re.findall(
                r"\b(?:MultiPoint|MultiLineString|MultiPolygon|Point|LineString|Polygon)\b",
                declared_geometry,
            ))
        else:
            allowed_geometry = set()
        if allowed_geometry and geometry["type"] not in allowed_geometry:
            raise CandidateRegistrationError(
                f"Feature geometry '{geometry['type']}' contradicts the declared schema for '{entry['datasetId']}'."
            )
        declared_coordinates = declared_geometry.get("coordinates") if isinstance(declared_geometry, dict) else ""
        if isinstance(declared_coordinates, str):
            coordinate_count = schema.get("coordinateCount")
            if coordinate_count is not None and len(geometry.get("coordinates", [])) != coordinate_count:
                raise CandidateRegistrationError(
                    f"Feature coordinate count contradicts the declared schema for '{entry['datasetId']}'."
                )
        if not isinstance(feature.get("properties"), dict):
            raise CandidateRegistrationError(
                f"Feature properties must be an object for '{entry['datasetId']}'."
            )

    def _validate_weather_snapshot(
        self, entry: Dict[str, Any], record: Dict[str, Any], payload: Dict[str, Any]
    ) -> None:
        schema = record["schema"]
        location = schema.get("location", {})
        current = schema.get("current", {})
        if (
            entry.get("recordCount") != 1
            or not isinstance(payload, dict)
            or not isinstance(payload.get("current"), dict)
            or not isinstance(payload.get("current_units"), dict)
            or not isinstance(location, dict)
            or not isinstance(current, dict)
            or any(name not in payload for name in location)
            or any(name not in payload["current"] for name in current)
            or any(name not in payload["current_units"] for name in current)
            or not isinstance(payload.get("_evidence"), dict)
            or payload["_evidence"].get("source") != "Open-Meteo Forecast API"
        ):
            raise CandidateRegistrationError("Open-Meteo snapshot does not conform to its declared schema/provenance.")

    @staticmethod
    def _coordinates_valid(coordinates: Any) -> bool:
        positions = []

        def visit(value: Any) -> None:
            if not isinstance(value, list):
                return
            if len(value) >= 2 and all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in value[:2]
            ):
                positions.append(value[:2])
                return
            for child in value:
                visit(child)

        visit(coordinates)
        return bool(positions) and all(
            math.isfinite(lon)
            and math.isfinite(lat)
            and -180 <= lon <= 180
            and -90 <= lat <= 90
            for lon, lat in positions
        )

    def _check_registry_conflicts(self, manifest: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
        for entry in manifest["datasets"]:
            record = next(item for item in records if item["capabilityId"] == entry["registryRecordId"])
            if self.capability_registry is not None:
                try:
                    self.capability_registry.get_capability(record["capabilityId"])
                except CapabilityNotFoundError:
                    pass
                else:
                    raise CandidateRegistrationError(
                        f"Candidate record ID '{record['capabilityId']}' already exists in the canonical registry."
                    )
            if self.dataset_registry is not None:
                try:
                    self.dataset_registry.get_by_dataset_id(entry["datasetId"])
                except PackageNotFoundError:
                    pass
                else:
                    raise CandidateRegistrationError(
                        f"Dataset ID '{entry['datasetId']}' already exists in the canonical dataset registry."
                    )

    def _check_mdu_contracts(
        self, manifest: Dict[str, Any], records: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        results = []
        for entry in manifest["datasets"]:
            record = next(item for item in records if item["capabilityId"] == entry["registryRecordId"])
            mdu_dataset_id = entry.get("mduDatasetId") or record.get("mduDatasetId")
            if not mdu_dataset_id:
                results.append({
                    "dataset_id": entry["datasetId"],
                    "status": "PENDING_MDU_MAPPING",
                    "reason": "The export contains no canonical MDU dataset ID; schema compatibility is not asserted.",
                })
                continue
            if self.mdu_contracts is None or not self.mdu_contracts.is_live():
                results.append({
                    "dataset_id": entry["datasetId"],
                    "mdu_dataset_id": mdu_dataset_id,
                    "status": "PENDING_MDU_CONTRACT",
                    "reason": "No live MDU contract is available; candidate remains noncanonical.",
                })
                continue
            try:
                contract = self.mdu_contracts.fetch_schema_contract(mdu_dataset_id)
            except MDUUnavailableError as exc:
                results.append({
                    "dataset_id": entry["datasetId"],
                    "mdu_dataset_id": mdu_dataset_id,
                    "status": "PENDING_MDU_CONTRACT",
                    "reason": str(exc),
                })
                continue
            if contract.get("dataset_id") not in (None, mdu_dataset_id):
                raise CandidateRegistrationError(
                    f"MDU schema dataset ID does not match candidate '{entry['datasetId']}'."
                )
            local_fields = record["schema"].get("fields")
            remote_fields = contract.get("fields")
            if not isinstance(local_fields, list) or not isinstance(remote_fields, list):
                results.append({
                    "dataset_id": entry["datasetId"],
                    "mdu_dataset_id": mdu_dataset_id,
                    "status": "PENDING_SCHEMA_MAPPING",
                    "reason": "The GEV export schema is descriptive and has no typed field mapping for MDU comparison.",
                })
                continue
            if local_fields != remote_fields:
                raise CandidateRegistrationError(
                    f"GEV schema does not match the live MDU schema for '{entry['datasetId']}'."
                )
            results.append({
                "dataset_id": entry["datasetId"],
                "mdu_dataset_id": mdu_dataset_id,
                "status": "PASS",
                "schema_version": contract.get("schema_version") or contract.get("version"),
            })
        pending = [item for item in results if item["status"] != "PASS"]
        return {
            "status": "PENDING" if pending else "PASS",
            "canonical_publication_allowed": False,
            "results": results,
        }

    def _validate_stored_candidate(self, bundle: Dict[str, Any]) -> None:
        if (
            bundle.get("candidate_package_id") != PACKET_ID
            or bundle.get("packet_version") != PACKET_VERSION
            or bundle.get("registration_status") != "PENDING_AUTHORIZATION"
            or bundle.get("canonical") is not False
            or bundle.get("discoverable") is not False
        ):
            raise CandidateRegistrationError("Stored GEV candidate is not in a valid noncanonical state.")
        manifest = bundle.get("manifest")
        records = bundle.get("registry_records")
        sidecar = bundle.get("dataset_records_sidecar")
        if (
            not isinstance(manifest, dict)
            or not isinstance(manifest.get("datasets"), list)
            or not isinstance(records, list)
            or not isinstance(sidecar, list)
            or records != sidecar
        ):
            raise CandidateRegistrationError("Stored GEV candidate metadata is invalid.")
        artifacts = bundle.get("artifacts")
        hashes = bundle.get("artifact_sha256")
        if not isinstance(artifacts, dict) or not isinstance(hashes, dict) or set(artifacts) != set(hashes):
            raise CandidateRegistrationError("Stored GEV candidate artifact inventory is invalid.")
        for filename, artifact in artifacts.items():
            if not isinstance(artifact, dict) or not isinstance(artifact.get("content"), str):
                raise CandidateRegistrationError(f"Stored GEV artifact '{filename}' is invalid.")
            actual_hash = hashlib.sha256(artifact["content"].encode("utf-8")).hexdigest()
            if actual_hash != artifact.get("sha256") or hashes.get(filename) != actual_hash:
                raise CandidateRegistrationError(f"Stored GEV artifact '{filename}' failed its integrity check.")
        if bundle.get("bundle_sha256") != self._bundle_sha256(bundle):
            raise CandidateRegistrationError("Stored GEV candidate failed its integrity check.")
        if len(records) != len(manifest["datasets"]):
            raise CandidateRegistrationError("Stored GEV candidate metadata inventory is invalid.")
        actual_source_hash = self._source_package_sha256(
            manifest,
            records,
            sidecar,
            hashes,
        )
        if bundle.get("source_package_sha256") not in (None, actual_source_hash):
            raise CandidateRegistrationError("Stored GEV source package metadata failed its integrity check.")

    def _read_artifact(self, relative: str) -> tuple[bytes, Any]:
        base = self.import_dir.resolve()
        path = (self.import_dir / relative).resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise CandidateRegistrationError(f"GEV artifact path escapes the import folder: '{relative}'.") from exc
        try:
            raw = path.read_bytes()
            payload = json.loads(raw, object_pairs_hook=GeospatialExportCandidateService._unique_object)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise CandidateRegistrationError(f"Unable to read valid GEV artifact '{relative}': {exc}") from exc
        return raw, payload

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=GeospatialExportCandidateService._unique_object,
            )
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise CandidateRegistrationError(f"Unable to read GEV package file '{path.name}': {exc}") from exc
        if not isinstance(payload, dict):
            raise CandidateRegistrationError(f"GEV package file '{path.name}' must contain a JSON object.")
        return payload

    @staticmethod
    def _unique_object(pairs: List[tuple]) -> Dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field '{key}'")
            result[key] = value
        return result

    @classmethod
    def _license_family(cls, value: Any) -> Optional[str]:
        normalized = cls._normalize(value or "")
        for family, aliases in _LICENSE_FAMILIES:
            if any(cls._normalize(alias) in normalized for alias in aliases):
                return family
        if (
            normalized in {"", "n/a", "na", "not identified", "not applicable"}
            or normalized.startswith("not applicable ")
        ):
            return None
        return normalized

    @staticmethod
    def _format_family(value: Any) -> str:
        normalized = " ".join(str(value or "").casefold().split())
        if normalized.startswith("geojson featurecollection"):
            return "geojson-featurecollection"
        if normalized.startswith("open-meteo json"):
            return "open-meteo-json"
        if normalized.startswith("json") and ("status" in normalized or "availability" in normalized):
            return "json-availability-status"
        return normalized

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())

    @classmethod
    def _meaningful_tokens(cls, value: Any) -> set:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", str(value).casefold())
            if token not in _NON_SOURCE_WORDS and (len(token) > 2 or token.isdigit())
        }

    @staticmethod
    def _bundle_sha256(bundle: Dict[str, Any]) -> str:
        payload = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _source_package_sha256(
        manifest: Any,
        records: Any,
        sidecar: Any,
        artifact_sha256: Any,
    ) -> str:
        source_package = {
            "manifest": manifest,
            "registry_records": records,
            "dataset_records_sidecar": sidecar,
            "artifact_sha256": artifact_sha256,
        }
        canonical = json.dumps(source_package, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _summary(bundle: Dict[str, Any]) -> Dict[str, Any]:
        entries = bundle["manifest"]["datasets"]
        return {
            "candidate_package_id": bundle["candidate_package_id"],
            "registration_status": bundle["registration_status"],
            "canonical": bundle["canonical"],
            "discoverable": bundle["discoverable"],
            "artifact_count": len(bundle["artifacts"]),
            "candidate_record_count": len(bundle["registry_records"]),
            "registered_by": bundle["registered_by"],
            "datasets": [
                {
                    "dataset_id": entry["datasetId"],
                    "external_record_id": entry["registryRecordId"],
                    "file": entry["file"],
                    "license": entry.get("license"),
                    "status": entry.get("status"),
                }
                for entry in entries
            ],
            "mdu_contract_validation": bundle["mdu_contract_validation"],
        }
