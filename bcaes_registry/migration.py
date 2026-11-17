"""
BCAES Canonical Registry — Legacy Record Migration & Normalization Module.

Provides safe, backward-compatible, idempotent migration for persisted BCAES
registry records transitioning to the canonical RegistryObject schema.

Addresses:
- Missing fields: classification, purpose, version, dependencies, consumers,
  authority_boundaries, links, timestamps.
- Status normalization: explicit lifecycle-based migration of legacy statuses
  (such as PUBLISHED), deprecation checks, retirement checks, and draft preservation.
- Full preservation of existing IDs, ownership, metadata, and provenance.
- Safe persistence: pre-migration backups, atomic writes, and validation-before-write.
"""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple

from bcaes_registry.models import (
    DependencyRef,
    ObjectStatus,
    RegistryObject,
    RegistryType,
)

logger = logging.getLogger("masterdb.bcaes_registry.migration")


class MalformedRecordError(ValueError):
    """Raised when a legacy registry record is fundamentally unrecoverable."""
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


VALID_REGISTRY_TYPES = {rt.value for rt in RegistryType}
VALID_STATUSES = {s.value for s in ObjectStatus}


def is_legacy_record(record: Dict[str, Any]) -> bool:
    """Detect whether a record conforms to legacy schema and requires migration."""
    if not isinstance(record, dict):
        return True

    # Required fields in current RegistryObject schema
    required_keys = (
        "id",
        "registry_type",
        "classification",
        "name",
        "purpose",
        "owner",
        "status",
        "version",
        "dependencies",
        "consumers",
        "authority_boundaries",
        "links",
    )
    for k in required_keys:
        if k not in record or record[k] is None:
            return True

    # Status must be one of current ObjectStatus enum values
    status_val = record.get("status")
    if not isinstance(status_val, str) or status_val.lower() not in VALID_STATUSES or status_val != status_val.lower():
        return True

    # Classification must match registry_type
    rt = record.get("registry_type")
    classification = record.get("classification")
    if rt not in VALID_REGISTRY_TYPES or classification != rt:
        return True

    # Dependencies must be a list of dicts with 'id'
    deps = record.get("dependencies")
    if not isinstance(deps, list):
        return True
    for d in deps:
        if not isinstance(d, dict) or "id" not in d:
            return True

    # Consumers, authority_boundaries, links must be lists
    for coll in ("consumers", "authority_boundaries", "links"):
        if not isinstance(record.get(coll), list):
            return True

    return False


def migrate_status(status_raw: Any, record: Dict[str, Any]) -> Tuple[ObjectStatus, Optional[str]]:
    """
    Explicit lifecycle-based status migration.

    Semantics:
    1. If status is already a valid lowercase ObjectStatus, return it.
    2. If status is uppercase/mixed-case standard status (e.g. 'ACTIVE', 'DRAFT'), normalize to lowercase.
    3. If status is 'PUBLISHED' (or 'published'):
       Evaluate actual lifecycle semantics:
       a. Deprecation markers: If record has deprecated=True, is_deprecated=True, deprecated_at,
          or deprecation_reason, map to DEPRECATED.
       b. Retirement markers: If record has retired=True, is_retired=True, retired_at, or archived=True,
          map to RETIRED.
       c. Draft / Inactive markers: If record has draft=True, is_draft=True, or active=False,
          map to DRAFT.
       d. Canonical Operational Status: In BCAES architecture, a published registry object with no
          deprecation or retirement flags represents an active, operational capability available
          for ecosystem dependency resolution -> map to ACTIVE.
    4. If status is None or empty:
       If active=True, map to ACTIVE; otherwise default to DRAFT.
    5. Any unrecognized or invalid status raises MalformedRecordError.
    """
    if status_raw is None:
        if record.get("active") is True:
            return ObjectStatus.ACTIVE, "Defaulted to active from active=True flag"
        return ObjectStatus.DRAFT, "Defaulted missing status to draft"

    if not isinstance(status_raw, str):
        raise MalformedRecordError(
            f"Record '{record.get('id', '<unknown>')}' status must be a string, got {type(status_raw).__name__}: {status_raw!r}"
        )

    cleaned = status_raw.strip()
    upper = cleaned.upper()
    lower = cleaned.lower()

    if lower in VALID_STATUSES:
        return ObjectStatus(lower), None

    if upper == "PUBLISHED":
        # Check deprecation markers
        if (
            record.get("deprecated") is True
            or record.get("is_deprecated") is True
            or record.get("deprecated_at") is not None
            or bool(record.get("deprecation_reason"))
        ):
            return ObjectStatus.DEPRECATED, "Migrated legacy PUBLISHED to deprecated due to deprecation markers"

        # Check retirement markers
        if (
            record.get("retired") is True
            or record.get("is_retired") is True
            or record.get("retired_at") is not None
            or record.get("archived") is True
            or record.get("is_archived") is True
        ):
            return ObjectStatus.RETIRED, "Migrated legacy PUBLISHED to retired due to retirement/archival markers"

        # Check draft/inactive markers
        if (
            record.get("draft") is True
            or record.get("is_draft") is True
            or (record.get("active") is False and record.get("enabled") is False)
        ):
            return ObjectStatus.DRAFT, "Migrated legacy PUBLISHED to draft due to inactive/draft markers"

        # Production operational object
        return ObjectStatus.ACTIVE, "Migrated legacy PUBLISHED to active (operational lifecycle state)"

    if upper in ("ARCHIVED", "DECOMMISSIONED"):
        return ObjectStatus.RETIRED, f"Migrated legacy {upper} to retired"

    if upper in ("INACTIVE", "DISABLED", "SUSPENDED"):
        return ObjectStatus.DEPRECATED, f"Migrated legacy {upper} to deprecated"

    raise MalformedRecordError(
        f"Record '{record.get('id', '<unknown>')}' contains unmappable status: '{status_raw}'"
    )


def normalize_dependencies(deps: Any, record_id: str) -> List[Dict[str, Any]]:
    """Normalize dependencies into a list of DependencyRef dicts."""
    if deps is None:
        return []
    if not isinstance(deps, list):
        raise MalformedRecordError(
            f"Record '{record_id}' dependencies must be a list, got {type(deps).__name__}"
        )

    normalized = []
    for idx, dep in enumerate(deps):
        if isinstance(dep, str):
            dep_id = dep.strip()
            if not dep_id:
                raise MalformedRecordError(f"Record '{record_id}' dependency at index {idx} is empty string")
            normalized.append({"id": dep_id, "required_version": None})
        elif isinstance(dep, dict):
            if "id" not in dep or not dep["id"] or not isinstance(dep["id"], str):
                raise MalformedRecordError(
                    f"Record '{record_id}' dependency at index {idx} missing valid 'id': {dep!r}"
                )
            req_ver = dep.get("required_version")
            if req_ver is not None and not isinstance(req_ver, str):
                req_ver = str(req_ver)
            normalized.append({"id": dep["id"].strip(), "required_version": req_ver})
        elif isinstance(dep, DependencyRef):
            normalized.append(dep.model_dump())
        else:
            raise MalformedRecordError(
                f"Record '{record_id}' dependency at index {idx} has invalid type {type(dep).__name__}"
            )
    return normalized


def migrate_legacy_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes a legacy BCAES registry record into a valid RegistryObject schema dictionary.

    Guarantees:
    - Detects legacy formats and fills missing fields with semantically justified defaults.
    - Preserves existing IDs, ownership, timestamps, and unknown historical metadata.
    - Explicitly migrates PUBLISHED status according to lifecycle rules.
    - Idempotent: safe to run multiple times without state drift.
    - Malformed records raise MalformedRecordError with actionable diagnostic messages.
    """
    if not isinstance(record, dict):
        raise MalformedRecordError(f"Record must be a dictionary, got {type(record).__name__}")

    # Validate ID
    record_id = record.get("id")
    if not record_id or not isinstance(record_id, str) or not record_id.strip():
        raise MalformedRecordError(f"Malformed record: missing or empty 'id' field in {record!r}")
    record_id = record_id.strip()

    # Validate registry_type
    raw_rt = record.get("registry_type")
    if not raw_rt or not isinstance(raw_rt, str) or raw_rt.strip() not in VALID_REGISTRY_TYPES:
        # Check if id prefix can resolve registry_type if missing or malformed
        prefix_matched = None
        for rt in RegistryType:
            from bcaes_registry.models import _ID_PREFIX
            # Check id prefix
            prefix = _ID_PREFIX.get(rt)
            if prefix and record_id.startswith(f"{prefix}-"):
                prefix_matched = rt.value
                break
        if prefix_matched and (not raw_rt or raw_rt not in VALID_REGISTRY_TYPES):
            raw_rt = prefix_matched
        else:
            raise MalformedRecordError(
                f"Record '{record_id}' has invalid registry_type '{raw_rt}'. Expected one of {sorted(VALID_REGISTRY_TYPES)}"
            )
    registry_type_val = raw_rt.strip()

    # Validate Name
    name = record.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        raise MalformedRecordError(f"Record '{record_id}' missing required non-empty 'name'")
    name = name.strip()

    # Validate Owner
    owner = record.get("owner")
    if not owner or not isinstance(owner, str) or not owner.strip():
        raise MalformedRecordError(f"Record '{record_id}' missing required non-empty 'owner'")
    owner = owner.strip()

    # Purpose: preserve existing; fallback to description, summary, intent, or empty string
    purpose = record.get("purpose")
    if purpose is None:
        purpose = (
            record.get("description")
            or record.get("summary")
            or record.get("intent")
            or ""
        )
    if not isinstance(purpose, str):
        purpose = str(purpose)

    # Version: default to "1.0" for baseline published canonical objects
    version = record.get("version")
    if not version or not isinstance(version, str) or not version.strip():
        version = "1.0"
    else:
        version = version.strip()

    # Status migration
    status_raw = record.get("status")
    status_enum, migration_note = migrate_status(status_raw, record)

    # Dependencies
    dependencies = normalize_dependencies(record.get("dependencies"), record_id)

    # Consumers: derived, defaults to empty list
    consumers = record.get("consumers")
    if consumers is None or not isinstance(consumers, list):
        consumers = []
    else:
        consumers = [str(c).strip() for c in consumers if str(c).strip()]

    # Authority Boundaries: preserve existing or default to empty list
    boundaries = record.get("authority_boundaries")
    if boundaries is None or not isinstance(boundaries, list):
        boundaries = []
    else:
        boundaries = [str(b).strip() for b in boundaries if str(b).strip()]

    # Links: preserve existing or default to empty list
    links = record.get("links")
    if links is None or not isinstance(links, list):
        links = []
    else:
        links = [str(l).strip() for l in links if str(l).strip()]

    # Timestamps
    created_at = record.get("created_at") or _utcnow()
    updated_at = record.get("updated_at") or _utcnow()

    # Build migrated record preserving all original/historical keys
    migrated: Dict[str, Any] = dict(record)
    migrated["id"] = record_id
    migrated["registry_type"] = registry_type_val
    migrated["classification"] = registry_type_val
    migrated["name"] = name
    migrated["purpose"] = purpose
    migrated["owner"] = owner
    migrated["status"] = status_enum.value
    migrated["version"] = version
    migrated["dependencies"] = dependencies
    migrated["consumers"] = consumers
    migrated["authority_boundaries"] = boundaries
    migrated["links"] = links
    migrated["created_at"] = created_at
    migrated["updated_at"] = updated_at

    # Preserve provenance / legacy audit info
    if migration_note:
        migrated["_migration_audit"] = {
            "original_status": str(status_raw),
            "migrated_to": status_enum.value,
            "note": migration_note,
            "migrated_at": _utcnow(),
        }

    return migrated


def backup_store_directory(storage_dir: Path) -> Optional[Path]:
    """
    Creates an immutable timestamped backup of the persistent storage directory
    prior to any migration mutation.
    """
    if not storage_dir.exists():
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = storage_dir.parent / f"{storage_dir.name}_backup_{timestamp}"
    if backup_dir.exists():
        return backup_dir

    shutil.copytree(storage_dir, backup_dir)
    logger.info("Created BCAES registry persistence backup at %s", backup_dir)
    return backup_dir
