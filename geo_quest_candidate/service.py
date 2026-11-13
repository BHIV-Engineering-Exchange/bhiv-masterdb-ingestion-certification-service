"""Validated local registration and controlled retrieval of GEO-QUEST artifacts."""
import hashlib
import hmac
import os
import json
import logging
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from services.artifact_store import ArtifactStore

logger = logging.getLogger("masterdb")

CAPABILITY_ID = "gev.aircraft_tracking"
DATASET_ID = "BHIV-GEO-QUEST-01-AIRCRAFT"
PROJECT_ROOT = Path(__file__).resolve().parent.parent / "MASTERDB-GEO-QUEST-01"
REQUIRED_CHECKS = {
    "CHK_01_RECORD_CONSERVATION",
    "CHK_02_IDENTIFIER_UNIQUENESS",
    "CHK_03_COORDINATE_VALIDITY",
    "CHK_04_NUMERIC_RANGE_VALIDITY",
    "CHK_05_TIMESTAMP_AGE_INTEGRITY",
    "CHK_06_PROVENANCE_COMPLETENESS",
}


class CandidateArtifactStore(Protocol):
    def load(self, key: str, /, *args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]: ...

    def save(self, key: str, value: Dict[str, Any], /, *args: Any, **kwargs: Any) -> Dict[str, Any]: ...


class CandidateRegistrationError(ValueError):
    """Raised when the candidate artifacts do not pass registration checks."""


class CandidateNotFoundError(KeyError):
    """Raised when the requested candidate capability has not been registered."""


class CandidateRetrieveRequest(BaseModel):
    center_latitude: float = Field(default=19.076, ge=-90, le=90)
    center_longitude: float = Field(default=72.8777, ge=-180, le=180)
    search_radius_nm: float = Field(default=100, gt=0, le=250)
    filter_hex_id: Optional[str] = None
    filter_callsign: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class GeoQuestCandidateService:
    def __init__(
        self,
        store_dir: str = "geo_quest_candidate_store",
        project_root: Path = PROJECT_ROOT,
        store: Optional[CandidateArtifactStore] = None,
    ) -> None:
        self.store: CandidateArtifactStore = store or ArtifactStore(reports_dir=store_dir)  # type: ignore[assignment]
        self.project_root = project_root

    def register_candidate(self, actor: str) -> Dict[str, Any]:
        existing = self.store.load(CAPABILITY_ID)
        if existing is not None:
            self._validate_bundle(existing)
            return self._registration_summary(existing)

        source = self._read_json("registration/source_record.json")
        dataset = self._read_json("registration/dataset_record.json")
        capability = self._read_json("registration/capability_record.json")
        metadata = self._read_json("metadata/aircraft_metadata.json")
        acquisition = self._read_json("raw/acquisition_metadata.json")
        raw = self._read_json("raw/aircraft_raw.json")
        cleaned = self._read_json("cleaned/aircraft_cleaned.json")
        quarantine = self._read_json("cleaned/aircraft_quarantine.json")
        report = self._read_json("validation/aircraft_quality_report.json")

        self._verify_normalization_pipeline(raw, acquisition, cleaned, quarantine)
        self._validate_artifacts(
            source, dataset, capability, metadata, acquisition, raw, cleaned, quarantine, report
        )
        records = cleaned["records"]
        bundle = {
            "capability_id": CAPABILITY_ID,
            "dataset_id": DATASET_ID,
            "registration_status": "PENDING_AUTHORIZATION",
            "canonical": False,
            "discoverable": False,
            "registered_by": actor,
            "source": source,
            "dataset": dataset,
            "capability": capability,
            "schema": dataset["schema"],
            "quality_report": report,
            "records": records,
        }
        bundle["bundle_sha256"] = self._bundle_sha256(bundle)
        bundle["bundle_signature_hmac"] = self._bundle_hmac_sha256(bundle)
        self.store.save(CAPABILITY_ID, bundle)
        logger.info(
            "geo_quest_candidate_registered capability_id=%s dataset_id=%s actor=%s records=%s",
            CAPABILITY_ID,
            DATASET_ID,
            actor,
            len(records),
        )
        return self._registration_summary(bundle)

    def get_candidate(self, capability_id: str) -> Dict[str, Any]:
        if capability_id != CAPABILITY_ID:
            raise CandidateNotFoundError(f"Candidate capability '{capability_id}' is not registered.")
        bundle = self.store.load(capability_id)
        if bundle is None:
            raise CandidateNotFoundError(f"Candidate capability '{capability_id}' is not registered.")
        self._validate_bundle(bundle)
        return {
            **self._registration_summary(bundle),
            "source": bundle["source"],
            "dataset": bundle["dataset"],
            "capability": bundle["capability"],
            "schema": bundle["schema"],
            "quality_report": bundle["quality_report"],
        }

    def retrieve(
        self, capability_id: str, request: CandidateRetrieveRequest
    ) -> Dict[str, Any]:
        if capability_id != CAPABILITY_ID:
            raise CandidateNotFoundError(f"Candidate capability '{capability_id}' is not registered.")
        bundle = self.store.load(capability_id)
        if bundle is None:
            raise CandidateNotFoundError(f"Candidate capability '{capability_id}' is not registered.")
        self._validate_bundle(bundle)

        hex_filter = request.filter_hex_id.strip().upper() if request.filter_hex_id else None
        callsign_filter = request.filter_callsign.strip().upper() if request.filter_callsign else None
        matched = []
        for record in bundle["records"]:
            if hex_filter and record["aircraft_hex_id"] != hex_filter:
                continue
            if callsign_filter and not (record.get("callsign") or "").startswith(callsign_filter):
                continue
            if self._distance_nm(
                request.center_latitude,
                request.center_longitude,
                record["latitude"],
                record["longitude"],
            ) > request.search_radius_nm:
                continue
            matched.append(record)

        return {
            "capability": {
                "capability_id": bundle["capability_id"],
                "status": "PROPOSED",
                "discoverable": False,
                "canonical": False,
            },
            "dataset_id": bundle["dataset_id"],
            "records": matched[request.offset : request.offset + request.limit],
            "query_metadata": {
                "center_latitude": request.center_latitude,
                "center_longitude": request.center_longitude,
                "search_radius_nm": request.search_radius_nm,
                "filter_hex_id": hex_filter,
                "filter_callsign": callsign_filter,
                "matched_record_count": len(matched),
                "returned_record_count": len(matched[request.offset : request.offset + request.limit]),
                "offset": request.offset,
                "limit": request.limit,
            },
            "provenance": {
                "source_name": bundle["source"]["source_name"],
                "source_url": bundle["dataset"]["source_reference"]["endpoint"],
                "licence": bundle["dataset"]["licence"],
                "schema_version": bundle["records"][0]["provenance"]["schema_version"],
                "registration_status": bundle["registration_status"],
            },
        }

    def _verify_normalization_pipeline(
        self,
        raw: Dict[str, Any],
        acquisition: Dict[str, Any],
        cleaned: Dict[str, Any],
        quarantine: Dict[str, Any],
    ) -> None:
        script = self.project_root / "scripts" / "clean_aircraft.py"
        if not script.is_file():
            raise CandidateRegistrationError(f"Normalization pipeline script is missing: '{script}'.")

        with TemporaryDirectory(prefix="geo-quest-normalize-") as temp_dir:
            temp_path = Path(temp_dir)
            expected_cleaned_path = temp_path / "cleaned.json"
            expected_quarantine_path = temp_path / "quarantine.json"
            command = [
                sys.executable,
                str(script),
                "--raw-file",
                str(self.project_root / "raw" / "aircraft_raw.json"),
                "--meta-file",
                str(self.project_root / "raw" / "acquisition_metadata.json"),
                "--cleaned-file",
                str(expected_cleaned_path),
                "--quarantine-file",
                str(expected_quarantine_path),
            ]
            try:
                process = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
            except OSError as exc:
                logger.exception("geo_quest_normalization_execution_failed")
                raise CandidateRegistrationError(f"Unable to execute the normalization pipeline: {exc}") from exc
            if process.returncode:
                logger.error(
                    "geo_quest_normalization_failed returncode=%s stderr=%s",
                    process.returncode,
                    process.stderr,
                )
                raise CandidateRegistrationError(
                    f"Normalization pipeline failed with exit code {process.returncode}: {process.stderr.strip()}"
                )
            expected_cleaned = self._read_json_path(expected_cleaned_path)
            expected_quarantine = self._read_json_path(expected_quarantine_path)

        expected_status = self._normalize_status(raw, acquisition, expected_cleaned, expected_quarantine)
        actual_status = self._normalize_status(raw, acquisition, cleaned, quarantine)
        if expected_status != "SUCCESS" or actual_status != "SUCCESS":
            raise CandidateRegistrationError("Raw data could not be normalized by the declared cleaning pipeline.")
        if (
            self._comparable_records(expected_cleaned["records"])
            != self._comparable_records(cleaned.get("records", []))
            or self._comparable_records(
                expected_quarantine.get("quarantined_records", []), "quarantined_at_utc"
            )
            != self._comparable_records(
                quarantine.get("quarantined_records", []), "quarantined_at_utc"
            )
        ):
            raise CandidateRegistrationError(
                "Cleaned or quarantined artifacts do not match the declared raw-data normalization pipeline."
            )

    @staticmethod
    def _normalize_status(
        raw: Dict[str, Any],
        acquisition: Dict[str, Any],
        cleaned: Dict[str, Any],
        quarantine: Dict[str, Any],
    ) -> str:
        counts = cleaned.get("dataset_metadata", {})
        raw_records = raw.get("ac")
        cleaned_records = cleaned.get("records")
        quarantined_records = quarantine.get("quarantined_records")
        if (
            not isinstance(counts, dict)
            or not isinstance(raw_records, list)
            or not isinstance(cleaned_records, list)
            or not isinstance(quarantined_records, list)
        ):
            return "INVALID"
        if (
            counts.get("total_raw_records") != len(raw_records)
            or counts.get("total_cleaned_records") != len(cleaned_records)
            or counts.get("total_quarantined_records") != len(quarantined_records)
            or counts.get("source_url") != acquisition.get("source_url")
            or counts.get("raw_acquisition_timestamp_utc") != acquisition.get("utc_acquisition_timestamp")
        ):
            return "INVALID"
        return "SUCCESS"

    @staticmethod
    def _comparable_records(records: List[Dict[str, Any]], timestamp_field: Optional[str] = None) -> List[Dict[str, Any]]:
        comparable = []
        for record in records:
            item = json.loads(json.dumps(record))
            if timestamp_field:
                item.pop(timestamp_field, None)
            provenance = item.get("provenance")
            if isinstance(provenance, dict):
                provenance.pop("cleaning_pipeline_utc", None)
            comparable.append(item)
        return comparable

    @staticmethod
    def _read_json_path(path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise CandidateRegistrationError(f"Unable to read pipeline output '{path}': {exc}") from exc
        if not isinstance(payload, dict):
            raise CandidateRegistrationError(f"Pipeline output '{path}' must contain a JSON object.")
        return payload

    def _validate_artifacts(
        self,
        source: Dict[str, Any],
        dataset: Dict[str, Any],
        capability: Dict[str, Any],
        metadata: Dict[str, Any],
        acquisition: Dict[str, Any],
        raw: Dict[str, Any],
        cleaned: Dict[str, Any],
        quarantine: Dict[str, Any],
        report: Dict[str, Any],
    ) -> None:
        checks = report.get("executed_checks", [])
        check_status = {item.get("check_id"): item.get("status") for item in checks}
        records = cleaned.get("records")
        raw_records = raw.get("ac")
        quarantined = quarantine.get("quarantined_records")
        if (
            report.get("overall_status") != "PASS"
            or not REQUIRED_CHECKS.issubset(check_status)
            or any(check_status[check] != "PASS" for check in REQUIRED_CHECKS)
        ):
            raise CandidateRegistrationError("GEO-QUEST quality report does not show all required checks passing.")
        if not isinstance(records, list) or not isinstance(raw_records, list) or not isinstance(quarantined, list):
            raise CandidateRegistrationError("GEO-QUEST raw, cleaned, and quarantine artifacts have invalid shapes.")
        if len(raw_records) != len(records) + len(quarantined):
            raise CandidateRegistrationError("GEO-QUEST raw/cleaned/quarantine record counts do not reconcile.")
        if len(records) != dataset.get("record_counts", {}).get("cleaned_record_count"):
            raise CandidateRegistrationError("Cleaned record count does not match the dataset registration record.")
        if metadata.get("dataset_id") != DATASET_ID or metadata.get("raw_record_count") != len(raw_records):
            raise CandidateRegistrationError("Source record count or identity does not match dataset metadata.")
        endpoint = dataset.get("source_reference", {}).get("endpoint")
        acquired_at = dataset.get("acquisition_timestamp_utc")
        if (
            source.get("source_name") != "adsb.lol"
            or source.get("endpoint_used") != endpoint
            or metadata.get("source_url") != endpoint
            or acquisition.get("source_url") != endpoint
            or acquisition.get("status") != "SUCCESS"
            or acquisition.get("http_status") != 200
            or (acquisition.get("live_data_collected") is not True and acquisition.get("synthetic_data") is not True)
            or acquisition.get("utc_acquisition_timestamp") != acquired_at
            or source.get("exact_acquisition_timestamp_utc") != acquired_at
            or metadata.get("collection_timestamp_utc") != acquired_at
        ):
            raise CandidateRegistrationError("Source acquisition evidence, endpoint, and timestamps do not agree.")
        report_counts = report.get("record_counts", {})
        if (
            report_counts.get("raw_record_count") != len(raw_records)
            or report_counts.get("cleaned_record_count") != len(records)
            or report_counts.get("quarantined_record_count") != len(quarantined)
        ):
            raise CandidateRegistrationError("Quality report counts do not match the source artifacts.")
        if capability.get("source_dataset_reference", {}).get("proposed_dataset_id") != DATASET_ID:
            raise CandidateRegistrationError("Capability does not reference the candidate dataset.")
        if dataset.get("proposed_dataset_id") != DATASET_ID:
            raise CandidateRegistrationError("GEO-QUEST source or candidate dataset identity is unexpected.")
        if dataset.get("source_reference", {}).get("source_name") != source.get("source_name"):
            raise CandidateRegistrationError("Candidate dataset does not reference its registered source.")
        if capability.get("capability_id") != CAPABILITY_ID or capability.get("discoverable") is not False:
            raise CandidateRegistrationError("GEO-QUEST capability must remain the non-discoverable proposed candidate.")
        if dataset.get("governance_notice", {}).get("canonical_registration_claimed") is not False:
            raise CandidateRegistrationError("GEO-QUEST candidate artifacts must not claim canonical registration.")

        dataset_fields = dataset.get("schema", {}).get("fields", [])
        metadata_fields = metadata.get("schema", {}).get("fields", [])
        fields = {item.get("name") for item in dataset_fields}
        metadata_schema = {item.get("name"): item for item in metadata_fields}
        if (
            len(fields) != len(dataset_fields)
            or len(metadata_schema) != len(metadata_fields)
            or fields != set(metadata_schema)
            or any(
                (field["type"], field["nullable"])
                != (metadata_schema[field["name"]].get("type"), metadata_schema[field["name"]].get("nullable"))
                for field in dataset_fields
            )
        ):
            raise CandidateRegistrationError("Candidate and metadata schema declarations do not agree.")
        if not fields or any(not isinstance(record, dict) or set(record) != fields for record in records):
            raise CandidateRegistrationError("Cleaned records do not conform to the declared candidate schema.")
        if len(fields) != dataset["schema"].get("field_count") or len(fields) != metadata.get("schema", {}).get("field_count", len(fields)):
            raise CandidateRegistrationError("Declared schema field count does not match its field definitions.")
        python_types = {
            "string": str,
            "integer": int,
            "float": (int, float),
            "boolean": bool,
            "object": dict,
        }
        identifiers = [record.get("aircraft_hex_id") for record in records]
        if any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
            raise CandidateRegistrationError("Cleaned aircraft identifiers must be present and unique.")
        for record in records:
            if any(
                (value is None and field["nullable"] is False)
                or (
                    value is not None
                    and (
                        field.get("type") not in python_types
                        or not isinstance(value, python_types[field["type"]])
                        or (field["type"] in {"integer", "float"} and isinstance(value, bool))
                    )
                )
                for field in dataset_fields
                for value in (record[field["name"]],)
            ):
                raise CandidateRegistrationError("Cleaned records contain values that violate schema field types.")
            lat, lon = record.get("latitude"), record.get("longitude")
            provenance = record.get("provenance")
            speed = record.get("ground_speed_kts")
            track = record.get("true_track_deg")
            altitude = record.get("altitude_baro_ft")
            ages = (record.get("position_age_seconds"), record.get("last_seen_seconds"))
            if (
                not isinstance(lat, (int, float))
                or not isinstance(lon, (int, float))
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
                or not isinstance(provenance, dict)
                or provenance.get("source_system") != source["source_name"]
                or provenance.get("source_url") != dataset["source_reference"].get("endpoint")
                or not provenance.get("raw_acquisition_utc")
                or (speed is not None and not 0 <= speed <= 1500)
                or (track is not None and not 0 <= track <= 360)
                or (altitude is not None and not -2000 <= altitude <= 85000)
                or any(age is not None and age < 0 for age in ages)
            ):
                raise CandidateRegistrationError("Cleaned records have invalid coordinates or incomplete provenance.")

    def _validate_bundle(self, bundle: Dict[str, Any]) -> None:
        if (
            bundle.get("capability_id") != CAPABILITY_ID
            or bundle.get("dataset_id") != DATASET_ID
            or bundle.get("canonical") is not False
            or bundle.get("discoverable") is not False
            or bundle.get("registration_status") != "PENDING_AUTHORIZATION"
        ):
            raise CandidateRegistrationError("Stored GEO-QUEST registration violates its candidate-only status.")
        records = bundle.get("records")
        if not isinstance(records, list) or not records:
            raise CandidateRegistrationError("Stored GEO-QUEST candidate has no validated records.")
        if bundle.get("bundle_sha256") != self._bundle_sha256(bundle):
            raise CandidateRegistrationError("Stored GEO-QUEST candidate failed its integrity check.")
        if "bundle_signature_hmac" in bundle:
            expected_hmac = self._bundle_hmac_sha256(bundle)
            if not hmac.compare_digest(str(bundle["bundle_signature_hmac"]), str(expected_hmac)):
                raise CandidateRegistrationError("Stored GEO-QUEST candidate failed authenticity verification (HMAC signature mismatch).")
        fields = {item.get("name") for item in bundle.get("schema", {}).get("fields", [])}
        if not fields or any(not isinstance(record, dict) or set(record) != fields for record in records):
            raise CandidateRegistrationError("Stored GEO-QUEST records no longer conform to the registered schema.")
        required_checks = {
            item.get("check_id"): item.get("status")
            for item in bundle.get("quality_report", {}).get("executed_checks", [])
        }
        if (
            bundle.get("quality_report", {}).get("overall_status") != "PASS"
            or any(required_checks.get(check) != "PASS" for check in REQUIRED_CHECKS)
        ):
            raise CandidateRegistrationError("Stored GEO-QUEST quality evidence is no longer valid.")

    def _read_json(self, relative_path: str) -> Dict[str, Any]:
        try:
            with (self.project_root / relative_path).open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise CandidateRegistrationError(f"Unable to load candidate artifact '{relative_path}': {exc}") from exc
        if not isinstance(payload, dict):
            raise CandidateRegistrationError(f"Candidate artifact '{relative_path}' must contain a JSON object.")
        return payload

    @staticmethod
    def _registration_summary(bundle: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "capability_id": bundle["capability_id"],
            "dataset_id": bundle["dataset_id"],
            "registration_status": bundle["registration_status"],
            "canonical": bundle["canonical"],
            "discoverable": bundle["discoverable"],
            "record_count": len(bundle["records"]),
            "registered_by": bundle["registered_by"],
        }

    @staticmethod
    def _distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        earth_radius_nm = 3440.065
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        haversine = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        haversine = min(1.0, max(0.0, haversine))
        return earth_radius_nm * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))

    @staticmethod
    def _bundle_sha256(bundle: Dict[str, Any]) -> str:
        payload = {key: value for key, value in bundle.items() if key not in ("bundle_sha256", "bundle_signature_hmac")}
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _bundle_hmac_sha256(bundle: Dict[str, Any], secret: Optional[str] = None) -> str:
        key = (secret or os.environ.get("GEO_QUEST_SIGNING_KEY") or os.environ.get("AUTH_JWT_SECRET") or "bhiv-masterdb-candidate-authenticity-key").encode("utf-8")
        payload = {key: value for key, value in bundle.items() if key not in ("bundle_sha256", "bundle_signature_hmac")}
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hmac.new(key, serialized.encode("utf-8"), hashlib.sha256).hexdigest()
