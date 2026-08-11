import shutil
import tempfile

import pytest

from bcaes_registry.models import RegisterObjectRequest, RegistryType
from bcaes_registry.service import BCAESRegistryService
from canonical_repository.models import DocumentCategory, PublishVersionRequest, RegisterDocumentRequest
from canonical_repository.service import CanonicalRepositoryService
from services.backup_service import (
    BackupError,
    export_snapshot,
    read_snapshot,
    restore_snapshot,
    write_snapshot,
)
from services.sql_artifact_store import SqlArtifactStore


@pytest.fixture
def tmp_dir():
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_export_snapshot_is_empty_but_valid_for_in_memory_services():
    bcaes = BCAESRegistryService()  # no persist_dir/artifact_store -> in-memory
    canonical = CanonicalRepositoryService()
    snapshot = export_snapshot({"bcaes_registry": bcaes.artifact_store, "canonical_repository": canonical.artifact_store})
    assert snapshot["stores"]["bcaes_registry"] == {"persisted": False, "records": []}
    assert snapshot["stores"]["canonical_repository"] == {"persisted": False, "records": []}


def test_export_snapshot_captures_real_records_from_sql_backend(tmp_dir):
    db_url = f"sqlite:///{tmp_dir}/test.db"
    bcaes = BCAESRegistryService(artifact_store=SqlArtifactStore(db_url, store_name="bcaes_registry"))
    bcaes.register(
        RegistryType.CAPABILITY,
        RegisterObjectRequest(name="Schema Validation", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )
    snapshot = export_snapshot({"bcaes_registry": bcaes.artifact_store})
    assert snapshot["stores"]["bcaes_registry"]["persisted"] is True
    assert len(snapshot["stores"]["bcaes_registry"]["records"]) == 1
    assert snapshot["stores"]["bcaes_registry"]["records"][0]["name"] == "Schema Validation"


def test_write_and_read_snapshot_round_trip(tmp_dir):
    snapshot = {"exported_at": "now", "stores": {"x": {"persisted": True, "records": [{"id": "1"}]}}}
    path = f"{tmp_dir}/backup.json"
    write_snapshot(snapshot, path)
    reloaded = read_snapshot(path)
    assert reloaded == snapshot


def test_read_snapshot_missing_file_raises(tmp_dir):
    with pytest.raises(BackupError):
        read_snapshot(f"{tmp_dir}/does-not-exist.json")


def test_full_backup_and_restore_cycle_bcaes_registry(tmp_dir):
    db_url_a = f"sqlite:///{tmp_dir}/original.db"
    db_url_b = f"sqlite:///{tmp_dir}/restored.db"

    original = BCAESRegistryService(artifact_store=SqlArtifactStore(db_url_a, store_name="bcaes_registry"))
    obj = original.register(
        RegistryType.PRODUCT,
        RegisterObjectRequest(name="MASTERDB", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )

    snapshot = export_snapshot({"bcaes_registry": original.artifact_store})
    backup_path = f"{tmp_dir}/backup.json"
    write_snapshot(snapshot, backup_path)

    # Simulate restoring into a brand new, empty database.
    fresh_target = BCAESRegistryService(artifact_store=SqlArtifactStore(db_url_b, store_name="bcaes_registry"))
    reloaded_snapshot = read_snapshot(backup_path)
    counts = restore_snapshot(reloaded_snapshot, {"bcaes_registry": fresh_target.artifact_store})
    assert counts["bcaes_registry"] == 1

    # A THIRD, fresh service instance against db_url_b proves it's really
    # persisted, not just present in the object we restored into.
    verifying = BCAESRegistryService(artifact_store=SqlArtifactStore(db_url_b, store_name="bcaes_registry"))
    restored_obj = verifying.get(RegistryType.PRODUCT, obj.id)
    assert restored_obj.name == "MASTERDB"


def test_full_backup_and_restore_cycle_canonical_repository(tmp_dir):
    db_url_a = f"sqlite:///{tmp_dir}/original.db"
    db_url_b = f"sqlite:///{tmp_dir}/restored.db"

    original = CanonicalRepositoryService(artifact_store=SqlArtifactStore(db_url_a, store_name="canonical_repository"))
    doc = original.register(
        RegisterDocumentRequest(category=DocumentCategory.BCAES_VOL_4, title="Vol 4", owner="Kavy"),
        actor="Kavy", actor_roles=["bcaes-editor"],
    )
    original.publish_version(
        doc.id, PublishVersionRequest(content="real content", change_note="n", published_by="Kavy"),
        actor="Kavy", actor_roles=["bcaes-editor"],
    )

    snapshot = export_snapshot({"canonical_repository": original.artifact_store})
    backup_path = f"{tmp_dir}/backup.json"
    write_snapshot(snapshot, backup_path)

    fresh_target = CanonicalRepositoryService(artifact_store=SqlArtifactStore(db_url_b, store_name="canonical_repository"))
    counts = restore_snapshot(read_snapshot(backup_path), {"canonical_repository": fresh_target.artifact_store})
    assert counts["canonical_repository"] == 1

    verifying = CanonicalRepositoryService(artifact_store=SqlArtifactStore(db_url_b, store_name="canonical_repository"))
    restored_doc = verifying.get(doc.id, actor="Kavy", actor_roles=["ecosystem-reader"])
    assert restored_doc.current_version == 2
    latest = verifying.latest_version(doc.id, actor="Kavy", actor_roles=["ecosystem-reader"])
    assert latest.content == "real content"


def test_restore_into_unconfigured_service_raises():
    snapshot = {"stores": {"bcaes_registry": {"persisted": True, "records": [{"id": "x", "name": "y"}]}}}
    with pytest.raises(BackupError):
        restore_snapshot(snapshot, {"bcaes_registry": None})


def test_restore_skips_stores_that_were_empty_at_export_time():
    snapshot = {"stores": {"bcaes_registry": {"persisted": False, "records": []}}}
    counts = restore_snapshot(snapshot, {"bcaes_registry": None})
    assert counts["bcaes_registry"] == 0
