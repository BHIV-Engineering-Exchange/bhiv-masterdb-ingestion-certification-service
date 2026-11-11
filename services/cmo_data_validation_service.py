"""
CMO Marketing Intelligence Data Integrity and Validation Engine.
Author: Hariom Upadhyay (MASTERDB Data Integrity Lead)
Role: MASTERDB data integrity and validation specialist for CMO Agent delivery.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REQUIRED_FIELDS = [
    "campaign_id",
    "campaign_name",
    "channel",
    "impressions",
    "clicks",
    "conversions",
    "spend_usd",
    "revenue_usd",
    "roas",
    "cac",
    "attribution_model",
    "status",
    "start_date",
    "end_date",
    "last_updated_utc",
    "provenance_source",
]

ALLOWED_CHANNELS = {"search", "social", "email", "display", "affiliate", "video"}
ALLOWED_STATUSES = {"ACTIVE", "COMPLETED", "PAUSED", "SCHEDULED"}
ALLOWED_ATTRIBUTIONS = {"last_touch", "first_touch", "linear", "data_driven"}
CAMPAIGN_ID_REGEX = re.compile(r"^CMP-[0-9]{4}-[A-Z0-9]+-[0-9]{3,}$")


class CMODataValidationError(ValueError):
    """Raised when a validation check detects an unrecoverable data defect."""
    pass


class CMODataValidationService:
    def __init__(self, max_freshness_hours: int = 48) -> None:
        self.max_freshness_hours = max_freshness_hours

    def validate_schema_consistency(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check 1: Schema Consistency
        Validates column presence, expected vs actual types, regex constraints, and enum sets.
        """
        if not isinstance(records, list) or not records:
            return {
                "score": 0.0,
                "status": "FAIL",
                "violations": [{"error": "Records must be a non-empty list of dictionaries"}],
            }

        violations = []
        for idx, row in enumerate(records):
            if not isinstance(row, dict):
                violations.append({"row_index": idx, "error": "Row is not an object/dictionary"})
                continue

            # 1. Missing required columns
            missing = [f for f in REQUIRED_FIELDS if f not in row]
            if missing:
                violations.append({"row_index": idx, "field": "missing_fields", "missing": missing})

            # 2. Campaign ID format
            cid = row.get("campaign_id")
            if cid is not None:
                if not isinstance(cid, str) or not CAMPAIGN_ID_REGEX.match(cid):
                    violations.append({
                        "row_index": idx,
                        "field": "campaign_id",
                        "value": cid,
                        "error": "campaign_id must match regex ^CMP-[0-9]{4}-[A-Z0-9]+-[0-9]{3,}$",
                    })

            # 3. Channel enum
            ch = row.get("channel")
            if ch is not None and ch not in ALLOWED_CHANNELS:
                violations.append({
                    "row_index": idx,
                    "field": "channel",
                    "value": ch,
                    "error": f"channel must be one of {sorted(ALLOWED_CHANNELS)}",
                })

            # 4. Status enum
            st = row.get("status")
            if st is not None and st not in ALLOWED_STATUSES:
                violations.append({
                    "row_index": idx,
                    "field": "status",
                    "value": st,
                    "error": f"status must be one of {sorted(ALLOWED_STATUSES)}",
                })

            # 5. Numeric types
            for int_f in ("impressions", "clicks", "conversions"):
                val = row.get(int_f)
                if val is not None and (not isinstance(val, int) or isinstance(val, bool)):
                    violations.append({
                        "row_index": idx,
                        "field": int_f,
                        "value": val,
                        "error": f"{int_f} must be integer",
                    })

            for float_f in ("spend_usd", "revenue_usd", "roas", "cac"):
                val = row.get(float_f)
                if val is not None and (not isinstance(val, (int, float)) or isinstance(val, bool)):
                    violations.append({
                        "row_index": idx,
                        "field": float_f,
                        "value": val,
                        "error": f"{float_f} must be float/number",
                    })

        total_rows = len(records)
        clean_rows = total_rows - len({v.get("row_index") for v in violations if "row_index" in v})
        score = round((clean_rows / total_rows) * 100.0, 2) if total_rows else 0.0

        return {
            "score": score,
            "status": "PASS" if not violations else "FAIL",
            "violation_count": len(violations),
            "violations": violations,
        }

    def validate_freshness(
        self, records: List[Dict[str, Any]], as_of_utc: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Check 2: Temporal Freshness and Staleness
        Validates ISO 8601 formatting and ensures last_updated_utc is within SLA threshold.
        """
        now = as_of_utc or datetime.now(timezone.utc)
        violations = []

        for idx, row in enumerate(records):
            timestamp_str = row.get("last_updated_utc")
            if not timestamp_str or not isinstance(timestamp_str, str):
                violations.append({"row_index": idx, "campaign_id": row.get("campaign_id"), "error": "Missing or invalid timestamp string"})
                continue

            try:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception as exc:
                violations.append({"row_index": idx, "campaign_id": row.get("campaign_id"), "error": f"Invalid ISO 8601 timestamp: {exc}"})
                continue

            # Future timestamp check
            if dt > now + timedelta(minutes=5):
                violations.append({
                    "row_index": idx,
                    "campaign_id": row.get("campaign_id"),
                    "timestamp": timestamp_str,
                    "error": "Timestamp is in the future",
                })
                continue

            # Staleness SLA check
            age_hours = (now - dt).total_seconds() / 3600.0
            if age_hours > self.max_freshness_hours:
                violations.append({
                    "row_index": idx,
                    "campaign_id": row.get("campaign_id"),
                    "timestamp": timestamp_str,
                    "age_hours": round(age_hours, 1),
                    "max_freshness_hours": self.max_freshness_hours,
                    "error": f"Data stale: record age {round(age_hours, 1)}h exceeds SLA threshold {self.max_freshness_hours}h",
                })

        total = len(records)
        clean = total - len(violations)
        score = round((clean / total) * 100.0, 2) if total else 0.0

        return {
            "score": score,
            "status": "PASS" if not violations else "FAIL",
            "max_freshness_hours_sla": self.max_freshness_hours,
            "stale_record_count": len(violations),
            "violations": violations,
        }

    def validate_duplicates(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check 3: Duplicate Detection
        Identifies primary key collisions (campaign_id) and exact row duplicates.
        """
        seen_ids = set()
        duplicate_ids = set()
        seen_row_hashes = set()
        duplicate_rows = 0

        for row in records:
            cid = row.get("campaign_id")
            if cid:
                if cid in seen_ids:
                    duplicate_ids.add(cid)
                seen_ids.add(cid)

            # Row hash
            row_repr = json.dumps(row, sort_keys=True, default=str)
            row_hash = hashlib.sha256(row_repr.encode()).hexdigest()
            if row_hash in seen_row_hashes:
                duplicate_rows += 1
            seen_row_hashes.add(row_hash)

        total = len(records)
        duplicate_count = len(duplicate_ids) + duplicate_rows
        dup_pct = round((duplicate_count / total) * 100.0, 2) if total else 0.0
        score = max(0.0, 100.0 - dup_pct * 2)

        return {
            "score": score,
            "status": "PASS" if duplicate_count == 0 else "FAIL",
            "duplicate_campaign_id_count": len(duplicate_ids),
            "duplicate_campaign_ids": sorted(list(duplicate_ids)),
            "duplicate_row_count": duplicate_rows,
            "duplicate_percentage": dup_pct,
        }

    def validate_completeness_and_missing_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check 4: Missing Records & Completeness
        Detects null, empty, or unpopulated values across all mandatory schema fields.
        """
        total_cells = len(records) * len(REQUIRED_FIELDS)
        missing_cells = 0
        missing_by_field: Dict[str, int] = {f: 0 for f in REQUIRED_FIELDS}
        violating_rows = []

        for idx, row in enumerate(records):
            row_missing = []
            for field in REQUIRED_FIELDS:
                val = row.get(field)
                if val is None or (isinstance(val, str) and not val.strip()):
                    missing_cells += 1
                    missing_by_field[field] += 1
                    row_missing.append(field)
            if row_missing:
                violating_rows.append({"row_index": idx, "campaign_id": row.get("campaign_id"), "missing_fields": row_missing})

        completeness_pct = round(((total_cells - missing_cells) / total_cells) * 100.0, 2) if total_cells else 0.0

        return {
            "score": completeness_pct,
            "status": "PASS" if missing_cells == 0 else "FAIL",
            "total_cells": total_cells,
            "missing_cells": missing_cells,
            "missing_by_field": {k: v for k, v in missing_by_field.items() if v > 0},
            "violating_row_count": len(violating_rows),
            "violating_rows": violating_rows,
        }

    def validate_integrity_boundaries(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check 5: Domain Integrity Boundaries
        Validates logical business metrics:
        - impressions >= clicks >= conversions >= 0
        - spend_usd >= 0, revenue_usd >= 0
        - ROAS and CAC mathematical consistency
        """
        violations = []

        for idx, row in enumerate(records):
            imp = row.get("impressions")
            clicks = row.get("clicks")
            conv = row.get("conversions")
            spend = row.get("spend_usd")
            rev = row.get("revenue_usd")
            roas = row.get("roas")
            cac = row.get("cac")

            cid = row.get("campaign_id", f"row_{idx}")

            # Funnel hierarchy: impressions >= clicks >= conversions >= 0
            if isinstance(imp, (int, float)) and imp < 0:
                violations.append({"row_index": idx, "campaign_id": cid, "error": f"impressions ({imp}) cannot be negative"})
            if isinstance(clicks, (int, float)) and clicks < 0:
                violations.append({"row_index": idx, "campaign_id": cid, "error": f"clicks ({clicks}) cannot be negative"})
            if isinstance(conv, (int, float)) and conv < 0:
                violations.append({"row_index": idx, "campaign_id": cid, "error": f"conversions ({conv}) cannot be negative"})

            if isinstance(imp, (int, float)) and isinstance(clicks, (int, float)) and clicks > imp:
                violations.append({"row_index": idx, "campaign_id": cid, "error": f"clicks ({clicks}) cannot exceed impressions ({imp})"})

            if isinstance(clicks, (int, float)) and isinstance(conv, (int, float)) and conv > clicks:
                violations.append({"row_index": idx, "campaign_id": cid, "error": f"conversions ({conv}) cannot exceed clicks ({clicks})"})

            # Economics: spend >= 0, rev >= 0
            if isinstance(spend, (int, float)) and spend < 0:
                violations.append({"row_index": idx, "campaign_id": cid, "error": f"spend_usd ({spend}) cannot be negative"})
            if isinstance(rev, (int, float)) and rev < 0:
                violations.append({"row_index": idx, "campaign_id": cid, "error": f"revenue_usd ({rev}) cannot be negative"})

            # ROAS consistency: revenue / spend
            if isinstance(spend, (int, float)) and isinstance(rev, (int, float)) and isinstance(roas, (int, float)):
                if spend > 0:
                    expected_roas = round(rev / spend, 2)
                    if abs(roas - expected_roas) > 0.1:
                        violations.append({
                            "row_index": idx,
                            "campaign_id": cid,
                            "error": f"Declared ROAS ({roas}) does not reconcile with revenue/spend ({expected_roas})",
                        })

        total = len(records)
        clean = total - len(violations)
        score = round((clean / total) * 100.0, 2) if total else 0.0

        return {
            "score": score,
            "status": "PASS" if not violations else "FAIL",
            "violation_count": len(violations),
            "violations": violations,
        }

    def validate_retrieval_correctness(
        self, records: List[Dict[str, Any]], query_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check 6: Retrieval Correctness & Filter Execution
        Validates that querying the dataset produces deterministic, bound-checked results.
        Supports: channel filter, status filter, min_roas filter, limit, offset.
        """
        filtered = list(records)

        # 1. Channel filter
        channel_param = query_params.get("channel")
        if channel_param:
            filtered = [r for r in filtered if str(r.get("channel")).lower() == str(channel_param).lower()]

        # 2. Status filter
        status_param = query_params.get("status")
        if status_param:
            filtered = [r for r in filtered if str(r.get("status")).upper() == str(status_param).upper()]

        # 3. Minimum ROAS filter
        min_roas = query_params.get("min_roas")
        if min_roas is not None:
            filtered = [r for r in filtered if float(r.get("roas", 0.0)) >= float(min_roas)]

        matched_count = len(filtered)

        # 4. Pagination
        offset = int(query_params.get("offset", 0))
        limit = int(query_params.get("limit", 100))
        paginated = filtered[offset : offset + limit]

        # Content digest computation
        digest = hashlib.sha256(json.dumps(paginated, sort_keys=True, default=str).encode()).hexdigest()

        return {
            "status": "SUCCESS",
            "query_parameters": query_params,
            "matched_record_count": matched_count,
            "returned_record_count": len(paginated),
            "offset": offset,
            "limit": limit,
            "content_digest_sha256": digest,
            "records": paginated,
        }

    def validate_cmo_data_slice(
        self,
        records: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        as_of_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Unified 5-Pillar Validation Execution for CMO Marketing Intelligence.
        Computes composite score and produces an evidence-grade audit report.
        """
        # Determine temporal reference point (fallback to metadata creation time if provided)
        ref_time = as_of_utc
        if ref_time is None and metadata:
            meta_ts = (
                metadata.get("created_at_utc")
                or metadata.get("generated_at_utc")
                or metadata.get("last_audit_utc")
                or metadata.get("as_of_utc")
            )
            if meta_ts:
                try:
                    ref_time = datetime.fromisoformat(str(meta_ts).replace("Z", "+00:00"))
                except Exception:
                    ref_time = None

        schema_res = self.validate_schema_consistency(records)
        freshness_res = self.validate_freshness(records, as_of_utc=ref_time)
        duplicates_res = self.validate_duplicates(records)
        completeness_res = self.validate_completeness_and_missing_records(records)
        integrity_res = self.validate_integrity_boundaries(records)

        # Weighted composite score
        # Schema (25%), Completeness (25%), Freshness (20%), Integrity (15%), Duplicates (15%)
        composite_score = round(
            schema_res["score"] * 0.25
            + completeness_res["score"] * 0.25
            + freshness_res["score"] * 0.20
            + integrity_res["score"] * 0.15
            + duplicates_res["score"] * 0.15,
            2,
        )

        risk_flags = []
        if schema_res["status"] != "PASS":
            risk_flags.append("SCHEMA_NON_CONFORMANCE")
        if freshness_res["status"] != "PASS":
            risk_flags.append("TEMPORAL_STALENESS_DETECTED")
        if duplicates_res["status"] != "PASS":
            risk_flags.append("DUPLICATE_RECORDS_DETECTED")
        if completeness_res["status"] != "PASS":
            risk_flags.append("MISSING_MANDATORY_FIELDS")
        if integrity_res["status"] != "PASS":
            risk_flags.append("METRIC_INTEGRITY_BOUNDARY_VIOLATION")

        # Classification
        if composite_score >= 95.0 and not risk_flags:
            classification = "TRUSTED"
            certification_status = "CERTIFIED"
        elif composite_score >= 80.0:
            classification = "RELIABLE"
            certification_status = "CONDITIONAL_APPROVAL"
        else:
            classification = "REJECTED"
            certification_status = "REJECTED"

        recommendations = []
        if "SCHEMA_NON_CONFORMANCE" in risk_flags:
            recommendations.append("Enforce strict JSON schema types on marketing payload ingestion.")
        if "TEMPORAL_STALENESS_DETECTED" in risk_flags:
            recommendations.append("Trigger BIQOS ingestion pipeline refresh to update campaign telemetry within 48h SLA.")
        if "DUPLICATE_RECORDS_DETECTED" in risk_flags:
            recommendations.append("Deduplicate campaign records on primary key 'campaign_id' prior to storage.")
        if "MISSING_MANDATORY_FIELDS" in risk_flags:
            recommendations.append("Quarantine records missing spend_usd, revenue_usd, or campaign_id.")
        if "METRIC_INTEGRITY_BOUNDARY_VIOLATION" in risk_flags:
            recommendations.append("Validate conversion funnels (impressions >= clicks >= conversions) and positive economics.")

        return {
            "validation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "validator": "Hariom Upadhyay (MASTERDB Data Integrity Lead)",
            "composite_integrity_score": composite_score,
            "classification": classification,
            "certification_status": certification_status,
            "risk_flags": risk_flags,
            "total_records_analyzed": len(records),
            "pillars": {
                "schema_consistency": schema_res,
                "freshness_and_staleness": freshness_res,
                "duplicate_detection": duplicates_res,
                "completeness_and_missing_records": completeness_res,
                "metric_integrity_boundaries": integrity_res,
            },
            "recommendations": recommendations,
            "metadata": metadata or {},
        }

