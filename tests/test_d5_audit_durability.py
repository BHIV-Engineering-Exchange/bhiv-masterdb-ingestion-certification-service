"""Tests for D5 Durable Persistence: CryptoAuditEmitter durability, restart survival, and tamper detection."""
import json
from pathlib import Path

import pytest

from services.artifact_store import ArtifactStore
from services.crypto_audit_emitter import (
    AuditCorruptionError,
    AuditEntry,
    AuditPersistenceError,
    CryptoAuditEmitter,
)
from services.sql_artifact_store import SqlArtifactStore


def test_d5_audit_default_in_memory_backward_compatibility():
    """Default constructor with no arguments remains purely in-memory and backward compatible."""
    emitter = CryptoAuditEmitter()
    assert emitter.store is None
    assert emitter.get_chain() == []
    assert emitter.verify_chain() is True
    assert emitter.is_consistent is True

    e1 = emitter.emit("system_boot", "kernel", {"boot_id": 1})
    e2 = emitter.emit("user_login", "alice", {"session_id": "s1"})

    assert len(emitter.get_chain()) == 2
    assert e2.previous_hash == e1.entry_hash
    assert emitter.verify_chain() is True
    assert emitter.state_hash == e2.entry_hash

    # Tampering in-memory chain detected
    tampered = AuditEntry(
        timestamp=e1.timestamp,
        event_type="malicious_edit",
        actor=e1.actor,
        payload=e1.payload,
        previous_hash=e1.previous_hash,
        entry_hash=e1.entry_hash,
    )
    emitter._chain[0] = tampered
    assert emitter.verify_chain() is False


def test_d5_audit_persistence_with_artifact_store(tmp_path: Path):
    """Audit events are persisted to disk via ArtifactStore."""
    store_dir = tmp_path / "audit_records"
    store = ArtifactStore(reports_dir=str(store_dir))
    emitter = CryptoAuditEmitter(store=store)

    assert emitter.store is store
    assert emitter.get_chain() == []

    e1 = emitter.emit("dataset_ingested", "pipeline", {"dataset_id": "ds-001"})
    e2 = emitter.emit("dataset_certified", "qa-lead", {"dataset_id": "ds-001", "grade": "A"})

    # Check files created on disk
    entry0_file = store_dir / "audit_entry_00000000.json"
    entry1_file = store_dir / "audit_entry_00000001.json"
    manifest_file = store_dir / "audit_manifest.json"

    assert entry0_file.exists()
    assert entry1_file.exists()
    assert manifest_file.exists()

    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["count"] == 2
    assert manifest_data["last_hash"] == e2.entry_hash


def test_d5_audit_restart_survival_and_chain_continuity(tmp_path: Path):
    """A new emitter instance reloading from existing store seamlessly recovers history and continues chain."""
    store_dir = tmp_path / "audit_records"
    store1 = ArtifactStore(reports_dir=str(store_dir))
    emitter1 = CryptoAuditEmitter(store=store1)

    e1 = emitter1.emit("event_1", "actor1", {"step": 1})
    e2 = emitter1.emit("event_2", "actor2", {"step": 2})
    e3 = emitter1.emit("event_3", "actor3", {"step": 3})
    assert emitter1.verify_chain() is True

    # Simulate process restart by instantiating a second emitter on the same store directory
    store2 = ArtifactStore(reports_dir=str(store_dir))
    emitter2 = CryptoAuditEmitter(store=store2)

    recovered_chain = emitter2.get_chain()
    assert len(recovered_chain) == 3
    assert recovered_chain[0].entry_hash == e1.entry_hash
    assert recovered_chain[1].entry_hash == e2.entry_hash
    assert recovered_chain[2].entry_hash == e3.entry_hash
    assert emitter2.verify_chain() is True
    assert emitter2.state_hash == e3.entry_hash

    # Emit a new event from emitter2; must link to the end of recovered chain
    e4 = emitter2.emit("event_4", "actor4", {"step": 4})
    assert e4.previous_hash == e3.entry_hash
    assert len(emitter2.get_chain()) == 4
    assert emitter2.verify_chain() is True


def test_d5_audit_tamper_detection_on_disk(tmp_path: Path):
    """Tampering with an on-disk audit record is detected upon reload and verify_chain fails."""
    store_dir = tmp_path / "audit_records"
    store = ArtifactStore(reports_dir=str(store_dir))
    emitter = CryptoAuditEmitter(store=store)

    emitter.emit("config_updated", "admin", {"setting": "safe"})
    emitter.emit("access_granted", "admin", {"user": "bob"})

    # Tamper with the first audit record directly on disk
    entry0_file = store_dir / "audit_entry_00000000.json"
    record = json.loads(entry0_file.read_text(encoding="utf-8"))
    record["payload"]["setting"] = "compromised"
    entry0_file.write_text(json.dumps(record), encoding="utf-8")

    # Reload into a new emitter instance
    store_reloaded = ArtifactStore(reports_dir=str(store_dir))
    emitter_reloaded = CryptoAuditEmitter(store=store_reloaded)

    assert len(emitter_reloaded.get_chain()) == 2
    # verify_chain MUST fail because the entry_hash doesn't match the tampered payload
    assert emitter_reloaded.verify_chain() is False


def test_d5_audit_manifest_tamper_detection(tmp_path: Path):
    """Tampering with the audit manifest (count or last_hash) causes verify_chain to fail."""
    store_dir = tmp_path / "audit_records"
    store = ArtifactStore(reports_dir=str(store_dir))
    emitter = CryptoAuditEmitter(store=store)

    emitter.emit("ev1", "actor1", {})
    emitter.emit("ev2", "actor2", {})

    manifest_file = store_dir / "audit_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["count"] = 999  # Malicious count mismatch
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    # Reload emitter
    emitter_reloaded = CryptoAuditEmitter(store=ArtifactStore(reports_dir=str(store_dir)))
    assert emitter_reloaded.verify_chain() is False
    assert emitter_reloaded.is_consistent is False


def test_d5_audit_environment_variable_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """MASTERDB_AUDIT_STORE_DIR environment variable configures persistent store automatically."""
    audit_dir = tmp_path / "env_audit_store"
    monkeypatch.setenv("MASTERDB_AUDIT_STORE_DIR", str(audit_dir))

    # Constructor with no arguments should pick up the env var
    emitter = CryptoAuditEmitter()
    assert emitter.store is not None
    assert emitter.store.reports_dir == audit_dir

    emitter.emit("env_event", "system", {"key": "val"})
    assert (audit_dir / "audit_entry_00000000.json").exists()


def test_d5_audit_sql_artifact_store_durability(tmp_path: Path):
    """CryptoAuditEmitter works with SqlArtifactStore (database-backed persistence)."""
    db_file = tmp_path / "test_audit.db"
    db_url = f"sqlite:///{db_file}"
    sql_store = SqlArtifactStore(database_url=db_url, store_name="crypto_audit")

    emitter1 = CryptoAuditEmitter(store=sql_store)
    e1 = emitter1.emit("db_ev1", "db_actor", {"row": 1})
    e2 = emitter1.emit("db_ev2", "db_actor", {"row": 2})
    assert emitter1.verify_chain() is True

    # New emitter with same database URL
    sql_store2 = SqlArtifactStore(database_url=db_url, store_name="crypto_audit")
    emitter2 = CryptoAuditEmitter(store=sql_store2)

    chain = emitter2.get_chain()
    assert len(chain) == 2
    assert chain[0].entry_hash == e1.entry_hash
    assert chain[1].entry_hash == e2.entry_hash
    assert emitter2.verify_chain() is True

    # Continue chain in DB
    e3 = emitter2.emit("db_ev3", "db_actor", {"row": 3})
    assert e3.previous_hash == e2.entry_hash
    assert emitter2.verify_chain() is True


def test_d5_audit_production_startup_without_audit_dir_fails(monkeypatch: pytest.MonkeyPatch):
    """Production startup without MASTERDB_AUDIT_STORE_DIR (or storage config) fails closed."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("MASTERDB_AUDIT_STORE_DIR", raising=False)
    monkeypatch.delenv("MASTERDB_STORAGE_DIR", raising=False)
    monkeypatch.delenv("MASTERDB_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="MASTERDB_AUDIT_STORE_DIR must be configured in production"):
        CryptoAuditEmitter()


def test_d5_audit_production_startup_with_unusable_dir_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Production startup with an unusable directory path fails fast."""
    unusable_file = tmp_path / "not_a_directory.txt"
    unusable_file.write_text("blocked", encoding="utf-8")

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MASTERDB_AUDIT_STORE_DIR", str(unusable_file))

    with pytest.raises(RuntimeError, match="unusable in production"):
        CryptoAuditEmitter()


def test_d5_audit_dev_test_mode_retains_in_memory_compatibility(monkeypatch: pytest.MonkeyPatch):
    """Development/test mode preserves in-memory operation without error when audit dir is absent."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("MASTERDB_AUDIT_STORE_DIR", raising=False)

    emitter = CryptoAuditEmitter()
    assert emitter.store is None
    assert emitter.is_consistent is True

    e = emitter.emit("dev_event", "dev_user", {"mode": "in_memory"})
    assert emitter.get_chain() == [e]
    assert emitter.verify_chain() is True


def test_d5_audit_entry_write_failure_does_not_report_success(tmp_path: Path):
    """If durable entry persistence fails, emit raises AuditPersistenceError and in-memory chain is unaffected."""

    class FailingEntryStore(ArtifactStore):
        def save(self, dataset_id: str, report: dict) -> dict:
            if dataset_id.startswith("audit_entry_"):
                raise OSError("Disk write failed for entry")
            return super().save(dataset_id, report)

    store = FailingEntryStore(reports_dir=str(tmp_path / "fail_entry"))
    emitter = CryptoAuditEmitter(store=store)

    with pytest.raises(AuditPersistenceError, match="Failed to persist audit entry"):
        emitter.emit("ev_fail", "actor1", {"data": 123})

    # The in-memory chain MUST NOT contain the unpersisted entry
    assert emitter.get_chain() == []
    assert emitter.verify_chain() is True


def test_d5_audit_manifest_write_failure_does_not_report_success(tmp_path: Path):
    """If manifest write fails, emit raises AuditPersistenceError, rolls back entry file, and leaves chain clean."""

    class FailingManifestStore(ArtifactStore):
        def save(self, dataset_id: str, report: dict) -> dict:
            if dataset_id == "audit_manifest":
                raise OSError("Disk write failed for manifest")
            return super().save(dataset_id, report)

    store_dir = tmp_path / "fail_manifest"
    store = FailingManifestStore(reports_dir=str(store_dir))
    emitter = CryptoAuditEmitter(store=store)

    with pytest.raises(AuditPersistenceError, match="Failed to update audit manifest"):
        emitter.emit("ev_fail_manifest", "actor1", {"data": 456})

    # The in-memory chain MUST NOT contain the unpersisted entry
    assert emitter.get_chain() == []
    # Orphaned entry file must be cleaned up
    assert not (store_dir / "audit_entry_00000000.json").exists()


def test_d5_audit_reload_detects_incomplete_or_inconsistent_records(tmp_path: Path):
    """Reload detects missing sequence entries or inconsistent manifest."""
    store_dir = tmp_path / "incomplete_store"
    store = ArtifactStore(reports_dir=str(store_dir))
    emitter = CryptoAuditEmitter(store=store)

    emitter.emit("step0", "a", {})
    emitter.emit("step1", "a", {})
    emitter.emit("step2", "a", {})
    assert len(emitter.get_chain()) == 3

    # Delete entry 1 to simulate incomplete persistence / dropped file
    (store_dir / "audit_entry_00000001.json").unlink()

    # Reload into a new emitter instance
    reloaded = CryptoAuditEmitter(store=ArtifactStore(reports_dir=str(store_dir)))
    assert reloaded.is_consistent is False
    assert "Incomplete audit store" in (reloaded.corruption_reason or "")
    assert reloaded.verify_chain() is False

    with pytest.raises(AuditCorruptionError, match="Incomplete audit store"):
        reloaded.reload_from_store(strict=True)


def test_d5_audit_reload_detects_manifest_hash_mismatch(tmp_path: Path):
    """Reload detects last_hash mismatch between manifest and last entry."""
    store_dir = tmp_path / "manifest_mismatch"
    store = ArtifactStore(reports_dir=str(store_dir))
    emitter = CryptoAuditEmitter(store=store)

    emitter.emit("ev1", "a", {})

    manifest_file = store_dir / "audit_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["last_hash"] = "f" * 64  # Fake mismatch
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    reloaded = CryptoAuditEmitter(store=ArtifactStore(reports_dir=str(store_dir)))
    assert reloaded.is_consistent is False
    assert "Manifest last_hash mismatch" in (reloaded.corruption_reason or "")
    assert reloaded.verify_chain() is False

    with pytest.raises(AuditCorruptionError, match="Manifest last_hash mismatch"):
        reloaded.reload_from_store(strict=True)
