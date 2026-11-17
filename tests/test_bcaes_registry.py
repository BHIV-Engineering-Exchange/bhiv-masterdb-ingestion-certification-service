"""
Regression and persistence safety tests for BCAES Canonical Registry.

Covers:
- Loading current-format records.
- Loading legacy records with missing fields.
- Explicit lifecycle migration of PUBLISHED records.
- Defaulting missing optional collections.
- Full preservation of IDs, ownership, timestamps, and custom metadata.
- Malformed legacy record diagnostic errors.
- Migration idempotency.
- Persistence across application restart / re-initialization.
- Persistence safety: No data loss during failed migration.
"""
import json
import os
from pathlib import Path
import pytest
import shutil
import tempfile

from bcaes_registry.migration import (
    MalformedRecordError,
    is_legacy_record,
    migrate_legacy_record,
    migrate_status,
)
from bcaes_registry.models import ObjectStatus, RegistryType
from bcaes_registry.store import CanonicalRegistryStore


def write_record_file(directory: Path, record: dict) -> Path:
    file_path = directory / f"{record['id']}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return file_path


@pytest.fixture
def temp_store_dir():
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestBCAESRegistryMigration:
    def test_load_current_format_records(self, temp_store_dir):
        """Current format records load directly without alteration."""
        current_record = {
            "id": "prd-001",
            "registry_type": "product",
            "classification": "product",
            "name": "Earth Engine Visualizer",
            "purpose": "Renders real-time geospatial layers",
            "owner": "GeospatialTeam",
            "status": "active",
            "version": "2.4",
            "dependencies": [{"id": "cap-tiles", "required_version": "1.0"}],
            "consumers": [],
            "authority_boundaries": ["GeospatialTeam"],
            "links": ["https://geo.bhiv.internal/docs"],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        write_record_file(temp_store_dir, current_record)

        store = CanonicalRegistryStore(persist_dir=str(temp_store_dir))
        obj = store.get(RegistryType.PRODUCT, "prd-001")

        assert obj.id == "prd-001"
        assert obj.name == "Earth Engine Visualizer"
        assert obj.classification == RegistryType.PRODUCT
        assert obj.status == ObjectStatus.ACTIVE
        assert obj.version == "2.4"
        assert len(obj.dependencies) == 1
        assert obj.dependencies[0].id == "cap-tiles"
        assert obj.dependencies[0].required_version == "1.0"
        assert obj.authority_boundaries == ["GeospatialTeam"]
        assert obj.links == ["https://geo.bhiv.internal/docs"]

    def test_load_legacy_records(self, temp_store_dir):
        """Legacy records with 8 missing attributes and PUBLISHED status load cleanly."""
        legacy_record = {
            "id": "cap-legacy001",
            "registry_type": "capability",
            "name": "Legacy Capability",
            "owner": "ArchTeam",
            "status": "PUBLISHED",
            # Missing: classification, purpose, version, dependencies, consumers, authority_boundaries, links
        }
        write_record_file(temp_store_dir, legacy_record)

        store = CanonicalRegistryStore(persist_dir=str(temp_store_dir))
        obj = store.get(RegistryType.CAPABILITY, "cap-legacy001")

        assert obj.id == "cap-legacy001"
        assert obj.classification == RegistryType.CAPABILITY
        assert obj.purpose == ""
        assert obj.version == "1.0"
        assert obj.status == ObjectStatus.ACTIVE
        assert obj.dependencies == []
        assert obj.consumers == []
        assert obj.authority_boundaries == []
        assert obj.links == []
        assert obj.owner == "ArchTeam"

    def test_migrating_published_records_correctly(self):
        """PUBLISHED status is migrated based on actual lifecycle semantics, not blindly mapped to active."""
        # 1. Standard active published capability
        rec_active = {"id": "cap-1", "registry_type": "capability", "name": "Cap 1", "owner": "Ops", "status": "PUBLISHED"}
        mig_active = migrate_legacy_record(rec_active)
        assert mig_active["status"] == "active"
        assert "_migration_audit" in mig_active
        assert mig_active["_migration_audit"]["original_status"] == "PUBLISHED"

        # 2. Published object with deprecation marker -> deprecated
        rec_deprecated = {
            "id": "cap-2",
            "registry_type": "capability",
            "name": "Cap 2",
            "owner": "Ops",
            "status": "PUBLISHED",
            "deprecated": True,
            "deprecation_reason": "Replaced by cap-v2",
        }
        mig_deprecated = migrate_legacy_record(rec_deprecated)
        assert mig_deprecated["status"] == "deprecated"

        # 3. Published object with retirement / archival marker -> retired
        rec_retired = {
            "id": "cap-3",
            "registry_type": "capability",
            "name": "Cap 3",
            "owner": "Ops",
            "status": "PUBLISHED",
            "archived": True,
        }
        mig_retired = migrate_legacy_record(rec_retired)
        assert mig_retired["status"] == "retired"

        # 4. Published object with draft/inactive marker -> draft
        rec_draft = {
            "id": "cap-4",
            "registry_type": "capability",
            "name": "Cap 4",
            "owner": "Ops",
            "status": "PUBLISHED",
            "draft": True,
        }
        mig_draft = migrate_legacy_record(rec_draft)
        assert mig_draft["status"] == "draft"

    def test_missing_optional_collections(self, temp_store_dir):
        """Missing optional collections default to empty lists, and string dependencies are normalized."""
        record_with_strings = {
            "id": "psv-strdep",
            "registry_type": "platform_service",
            "name": "Platform Svc",
            "owner": "CoreTeam",
            "status": "draft",
            "dependencies": ["cap-auth", "dom-identity"],
        }
        write_record_file(temp_store_dir, record_with_strings)

        store = CanonicalRegistryStore(persist_dir=str(temp_store_dir))
        obj = store.get(RegistryType.PLATFORM_SERVICE, "psv-strdep")

        assert len(obj.dependencies) == 2
        assert obj.dependencies[0].id == "cap-auth"
        assert obj.dependencies[0].required_version is None
        assert obj.dependencies[1].id == "dom-identity"
        assert obj.authority_boundaries == []
        assert obj.links == []
        assert obj.consumers == []

    def test_preservation_of_record_ids_and_metadata(self, temp_store_dir):
        """Record IDs, provenance, custom attributes, and original timestamps are fully preserved."""
        legacy_rich = {
            "id": "dom-core-geo",
            "registry_type": "domain",
            "name": "Geospatial Core",
            "owner": "SpatialOps",
            "status": "PUBLISHED",
            "description": "Legacy description field mapped to purpose",
            "custom_metadata": {"cluster": "us-east-1", "tier": "gold"},
            "created_at": "2024-06-15T08:30:00Z",
            "tags": ["spatial", "mapping"],
        }
        write_record_file(temp_store_dir, legacy_rich)

        store = CanonicalRegistryStore(persist_dir=str(temp_store_dir))
        obj = store.get(RegistryType.DOMAIN, "dom-core-geo")

        assert obj.id == "dom-core-geo"
        assert obj.purpose == "Legacy description field mapped to purpose"
        assert obj.created_at == "2024-06-15T08:30:00Z"

        # Check persisted JSON preserves custom historical fields
        saved_file = temp_store_dir / "dom-core-geo.json"
        with open(saved_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        assert persisted["custom_metadata"] == {"cluster": "us-east-1", "tier": "gold"}
        assert persisted["tags"] == ["spatial", "mapping"]

    def test_malformed_legacy_records(self):
        """Malformed legacy records produce actionable diagnostic errors."""
        # Missing id
        with pytest.raises(MalformedRecordError, match="missing or empty 'id'"):
            migrate_legacy_record({"registry_type": "domain", "name": "No ID", "owner": "Ops"})

        # Missing name
        with pytest.raises(MalformedRecordError, match="missing required non-empty 'name'"):
            migrate_legacy_record({"id": "dom-1", "registry_type": "domain", "owner": "Ops"})

        # Missing owner
        with pytest.raises(MalformedRecordError, match="missing required non-empty 'owner'"):
            migrate_legacy_record({"id": "dom-1", "registry_type": "domain", "name": "No Owner"})

        # Invalid registry_type
        with pytest.raises(MalformedRecordError, match="invalid registry_type"):
            migrate_legacy_record({"id": "xyz-1", "registry_type": "nonexistent_type", "name": "X", "owner": "Ops"})

        # Unrecognized status
        with pytest.raises(MalformedRecordError, match="unmappable status"):
            migrate_legacy_record({"id": "dom-1", "registry_type": "domain", "name": "X", "owner": "Ops", "status": "UNKNOWN_GARBAGE"})

        # Invalid dependencies format
        with pytest.raises(MalformedRecordError, match="dependencies must be a list"):
            migrate_legacy_record({"id": "dom-1", "registry_type": "domain", "name": "X", "owner": "Ops", "dependencies": "not-a-list"})

    def test_migration_idempotency(self, temp_store_dir):
        """Migration is idempotent: multiple reloads and passes produce identical state."""
        legacy = {
            "id": "itg-kafka-pipeline",
            "registry_type": "integration",
            "name": "Kafka Event Pipeline",
            "owner": "PravahTeam",
            "status": "PUBLISHED",
        }
        write_record_file(temp_store_dir, legacy)

        # First load triggers migration
        store = CanonicalRegistryStore(persist_dir=str(temp_store_dir))
        obj1 = store.get(RegistryType.INTEGRATION, "itg-kafka-pipeline")
        assert obj1.status == ObjectStatus.ACTIVE

        file_after_migration = (temp_store_dir / "itg-kafka-pipeline.json").read_text(encoding="utf-8")

        # Second reload: should not modify file or state
        store.reload_from_persistent_store()
        obj2 = store.get(RegistryType.INTEGRATION, "itg-kafka-pipeline")
        assert obj2.status == ObjectStatus.ACTIVE

        file_after_reload = (temp_store_dir / "itg-kafka-pipeline.json").read_text(encoding="utf-8")
        assert file_after_migration == file_after_reload

    def test_persistence_after_application_restart(self, temp_store_dir):
        """Persisted migrated records survive process restart with a fresh store instance."""
        legacy = {
            "id": "frw-tantra-core",
            "registry_type": "framework",
            "name": "Tantra Framework",
            "owner": "ArchTeam",
            "status": "PUBLISHED",
        }
        write_record_file(temp_store_dir, legacy)

        # Instance A migrates and persists
        store_a = CanonicalRegistryStore(persist_dir=str(temp_store_dir))
        obj_a = store_a.get(RegistryType.FRAMEWORK, "frw-tantra-core")
        assert obj_a.status == ObjectStatus.ACTIVE

        # Destroy instance A, create instance B against same directory
        del store_a
        store_b = CanonicalRegistryStore(persist_dir=str(temp_store_dir))
        obj_b = store_b.get(RegistryType.FRAMEWORK, "frw-tantra-core")

        assert obj_b.id == "frw-tantra-core"
        assert obj_b.classification == RegistryType.FRAMEWORK
        assert obj_b.version == "1.0"
        assert obj_b.status == ObjectStatus.ACTIVE

    def test_no_data_loss_during_failed_migration(self, temp_store_dir):
        """If any record in the batch fails validation, original data is untouched and not overwritten."""
        valid_legacy = {
            "id": "eng-eval",
            "registry_type": "engine",
            "name": "Evaluation Engine",
            "owner": "EvalTeam",
            "status": "PUBLISHED",
        }
        corrupted = {
            "id": "eng-corrupt",
            "registry_type": "engine",
            # missing name and owner completely
            "status": "BOGUS_STATUS",
        }
        valid_path = write_record_file(temp_store_dir, valid_legacy)
        corrupt_path = write_record_file(temp_store_dir, corrupted)

        original_valid_content = valid_path.read_text(encoding="utf-8")
        original_corrupt_content = corrupt_path.read_text(encoding="utf-8")

        # Initialization must fail with diagnostic error
        with pytest.raises(MalformedRecordError):
            CanonicalRegistryStore(persist_dir=str(temp_store_dir))

        # Original files must remain intact without data loss or partial writes
        assert valid_path.read_text(encoding="utf-8") == original_valid_content
        assert corrupt_path.read_text(encoding="utf-8") == original_corrupt_content
