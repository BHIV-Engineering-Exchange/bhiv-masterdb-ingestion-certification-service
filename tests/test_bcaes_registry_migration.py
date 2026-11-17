# Tests for legacy registry migration
import json
import os
import pytest
from bcaes_registry.store import CanonicalRegistryStore
from bcaes_registry.models import ObjectStatus, RegistryType

def write_legacy_record(tmp_path, record):
    # Write a single JSON file to simulate persisted record
    record_path = tmp_path / f"{record['id']}.json"
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(record, f)
    return record_path

@pytest.fixture
def legacy_store(tmp_path):
    # Create a legacy record with missing fields and PUBLISHED status
    legacy = {
        "id": "cap-legacy123",
        "registry_type": "capability",
        "name": "Legacy Capability",
        "owner": "LegacyOwner",
        "status": "PUBLISHED",
        # missing classification, purpose, version, dependencies, authority_boundaries, links
    }
    write_legacy_record(tmp_path, legacy)
    store = CanonicalRegistryStore(persist_dir=str(tmp_path))
    return store

def test_legacy_record_migrated(legacy_store):
    obj = legacy_store.get(RegistryType.CAPABILITY, "cap-legacy123")
    assert obj.id == "cap-legacy123"
    # Classification should default to registry_type
    assert obj.classification == RegistryType.CAPABILITY
    # Purpose default to empty string
    assert obj.purpose == ""
    # Version default to "1.0"
    assert obj.version == "1.0"
    # Status should be mapped to ACTIVE
    assert obj.status == ObjectStatus.ACTIVE
    # Missing list fields default to empty lists
    assert obj.dependencies == []
    assert obj.authority_boundaries == []
    assert obj.links == []
    assert obj.consumers == []

def test_idempotent_reload(legacy_store):
    # Reload should not change the object or raise errors
    legacy_store.reload_from_persistent_store()
    obj = legacy_store.get(RegistryType.CAPABILITY, "cap-legacy123")
    assert obj.status == ObjectStatus.ACTIVE

def test_new_format_record_load(tmp_path):
    # Create a record that already matches new schema
    new_record = {
        "id": "prd-new001",
        "registry_type": "product",
        "classification": "product",
        "name": "New Product",
        "purpose": "Purpose",
        "owner": "Owner",
        "status": "draft",
        "version": "2.0",
        "dependencies": [],
        "authority_boundaries": [],
        "links": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    write_legacy_record(tmp_path, new_record)
    store = CanonicalRegistryStore(persist_dir=str(tmp_path))
    obj = store.get(RegistryType.PRODUCT, "prd-new001")
    assert obj.status.value == "draft"
    assert obj.classification == RegistryType.PRODUCT
