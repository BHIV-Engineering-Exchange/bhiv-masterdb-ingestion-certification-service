"""
Tests for Phase 3: Production Persistence Mode and Startup Safety.

Verifies:
1. Production mode fails closed when persistence configuration is absent.
2. Production mode rejects explicitly ephemeral/in-memory database configurations.
3. Production mode accepts supported persistent storage (file SQLite, PostgreSQL, storage dir).
4. Unfamiliar supported SQLAlchemy schemes are not improperly rejected.
5. Development and test modes preserve pure in-memory default behavior.
6. /ready readiness probe does not falsely report success in production when persistence is absent/failing.
7. /ready readiness probe verifies live persistence health.
8. Sensitive credentials and passwords in connection strings are sanitized from error messages and reports.
"""
import importlib
import os
import pytest
from fastapi.testclient import TestClient

import main
from services import startup_config
from services.artifact_store import ArtifactStore
from services.sql_artifact_store import SqlArtifactStore


# ---------------------------------------------------------------------------
# Unit tests for persistence evaluation and sanitization
# ---------------------------------------------------------------------------


def test_is_ephemeral_db_url_detects_in_memory_targets():
    # Explicit :memory: targets
    assert startup_config.is_ephemeral_db_url(":memory:") is True
    assert startup_config.is_ephemeral_db_url("sqlite:///:memory:") is True
    assert startup_config.is_ephemeral_db_url("sqlite://:memory:") is True
    assert startup_config.is_ephemeral_db_url("sqlite:///:memory:?cache=shared") is True
    assert startup_config.is_ephemeral_db_url("sqlite://") is True
    assert startup_config.is_ephemeral_db_url("sqlite:///") is True
    assert startup_config.is_ephemeral_db_url("sqlite:///app.db?mode=memory") is True
    assert startup_config.is_ephemeral_db_url("memory://") is True
    assert startup_config.is_ephemeral_db_url("mock://") is True

    # Persistent targets must NOT be detected as ephemeral
    assert startup_config.is_ephemeral_db_url("sqlite:///data.db") is False
    assert startup_config.is_ephemeral_db_url("sqlite:////var/data/app.db") is False
    assert startup_config.is_ephemeral_db_url("sqlite:///C:/data/app.db") is False
    assert startup_config.is_ephemeral_db_url("postgresql://user:pass@host:5432/db") is False
    assert startup_config.is_ephemeral_db_url("mysql://user:pass@host/db") is False
    assert startup_config.is_ephemeral_db_url("cockroachdb://user:pass@host:26257/db") is False


def test_sanitize_db_url_masks_passwords():
    raw_url = "postgresql://dbuser:supersecretpass123@db.prod.internal:5432/masterdb"
    sanitized = startup_config.sanitize_db_url(raw_url)
    assert "supersecretpass123" not in sanitized
    assert ":***@" in sanitized
    assert "dbuser" in sanitized

    # SQLite file url with no password remains unharmed
    file_url = "sqlite:///var/data/app.db"
    assert startup_config.sanitize_db_url(file_url) == file_url


def test_validate_production_persistence_absent_fails():
    ok, err = startup_config.validate_production_persistence(storage_dir=None, database_url=None)
    assert ok is False
    assert "Production mode requires persistent storage configuration" in err
    assert "Ephemeral in-memory storage is not permitted" in err


def test_validate_production_persistence_ephemeral_db_fails():
    ok, err = startup_config.validate_production_persistence(storage_dir=None, database_url="sqlite:///:memory:")
    assert ok is False
    assert "is ephemeral and cannot be used in production mode" in err


def test_validate_production_persistence_ephemeral_overrides_storage_dir():
    # Database URL takes priority; if explicitly ephemeral, must fail closed
    ok, err = startup_config.validate_production_persistence(
        storage_dir="/var/data", database_url="sqlite:///:memory:"
    )
    assert ok is False
    assert "is ephemeral and cannot be used in production mode" in err


def test_validate_production_persistence_malformed_db_fails():
    ok, err = startup_config.validate_production_persistence(
        storage_dir=None, database_url="not-a-url-scheme"
    )
    assert ok is False
    assert "malformed" in err


def test_validate_production_persistence_accepts_file_sqlite(tmp_path):
    db_file = str(tmp_path / "masterdb.sqlite")
    ok, err = startup_config.validate_production_persistence(
        storage_dir=None, database_url=f"sqlite:///{db_file}"
    )
    assert ok is True
    assert err is None


def test_validate_production_persistence_accepts_postgresql():
    ok, err = startup_config.validate_production_persistence(
        storage_dir=None, database_url="postgresql://usr:pwd@dbhost:5432/masterdb"
    )
    assert ok is True
    assert err is None


def test_validate_production_persistence_accepts_unfamiliar_schemes():
    # CockroachDB, MySQL, MariaDB, etc. supported by SQLAlchemy
    ok, err = startup_config.validate_production_persistence(
        storage_dir=None, database_url="cockroachdb://usr:pwd@dbhost:26257/masterdb"
    )
    assert ok is True
    assert err is None


def test_validate_production_persistence_accepts_storage_dir(tmp_path):
    ok, err = startup_config.validate_production_persistence(
        storage_dir=str(tmp_path), database_url=None
    )
    assert ok is True
    assert err is None


# ---------------------------------------------------------------------------
# Integration tests for main module reload and startup guard
# ---------------------------------------------------------------------------


def test_production_startup_fails_closed_when_persistence_absent(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-secret-at-least-32-bytes-long-for-testing")
    monkeypatch.delenv("MASTERDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("MASTERDB_STORAGE_DIR", raising=False)

    try:
        with pytest.raises(RuntimeError) as exc_info:
            importlib.reload(main)
        assert "Production mode requires persistent storage configuration" in str(exc_info.value)
    finally:
        # Restore environment and reload in clean non-production state
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
        importlib.reload(main)


def test_production_startup_fails_closed_with_ephemeral_sqlite(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-secret-at-least-32-bytes-long-for-testing")
    monkeypatch.setenv("MASTERDB_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("MASTERDB_STORAGE_DIR", raising=False)

    try:
        with pytest.raises(RuntimeError) as exc_info:
            importlib.reload(main)
        assert "is ephemeral and cannot be used in production mode" in str(exc_info.value)
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
        monkeypatch.delenv("MASTERDB_DATABASE_URL", raising=False)
        importlib.reload(main)


def test_production_startup_succeeds_with_persistent_storage_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-secret-at-least-32-bytes-long-for-testing")
    monkeypatch.delenv("MASTERDB_DATABASE_URL", raising=False)
    monkeypatch.setenv("MASTERDB_STORAGE_DIR", str(tmp_path))

    try:
        importlib.reload(main)
        assert main.bcaes_registry_service.artifact_store is not None
        assert isinstance(main.bcaes_registry_service.artifact_store, ArtifactStore)
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
        monkeypatch.delenv("MASTERDB_STORAGE_DIR", raising=False)
        importlib.reload(main)


def test_production_startup_succeeds_with_file_sqlite(monkeypatch, tmp_path):
    db_file = tmp_path / "prod_test.db"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-secret-at-least-32-bytes-long-for-testing")
    monkeypatch.setenv("MASTERDB_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("MASTERDB_STORAGE_DIR", raising=False)

    try:
        importlib.reload(main)
        assert main.bcaes_registry_service.artifact_store is not None
        assert isinstance(main.bcaes_registry_service.artifact_store, SqlArtifactStore)
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
        monkeypatch.delenv("MASTERDB_DATABASE_URL", raising=False)
        importlib.reload(main)


def test_development_mode_preserves_in_memory_default(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("MASTERDB_ENV", raising=False)
    monkeypatch.delenv("MASTERDB_DATABASE_URL", raising=False)
    monkeypatch.delenv("MASTERDB_STORAGE_DIR", raising=False)

    importlib.reload(main)
    report = startup_config.validate_configuration()
    assert report["persistence"]["mode"] == "in_memory"


# ---------------------------------------------------------------------------
# Health and readiness probe behavior
# ---------------------------------------------------------------------------


def test_health_probe_always_succeeds():
    client = TestClient(main.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_probe_in_dev_mode_preserves_contract():
    client = TestClient(main.app)
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["checks"]["bcaes_registry"] == "ok"
    assert data["checks"]["canonical_repository"] == "ok"


def test_ready_probe_in_production_fails_when_in_memory(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    # In-memory store (artifact_store is None)
    monkeypatch.setattr(main.bcaes_registry_service._store, "_artifact_store", None)

    client = TestClient(main.app)
    resp = client.get("/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert "error: Ephemeral in-memory storage is not permitted" in data["checks"]["persistence"]


def test_ready_probe_in_production_succeeds_with_verified_store(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "production")
    db_file = tmp_path / "ready_probe.db"
    store = SqlArtifactStore(f"sqlite:///{db_file}", store_name="bcaes_registry")
    monkeypatch.setattr(main.bcaes_registry_service._store, "_artifact_store", store)

    client = TestClient(main.app)
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["checks"]["persistence"] == "ok"


def test_ready_probe_in_production_fails_when_persistence_broken(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")

    class BrokenStore:
        def ping(self):
            raise ConnectionError("Database cluster unreachable")

    monkeypatch.setattr(main.bcaes_registry_service._store, "_artifact_store", BrokenStore())

    client = TestClient(main.app)
    resp = client.get("/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert "Database cluster unreachable" in data["checks"]["persistence"]


def test_credentials_sanitized_in_production_startup_exception(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "stable-secret-at-least-32-bytes-long-for-testing")
    monkeypatch.setenv("MASTERDB_DATABASE_URL", "sqlite://dbuser:super_secret_password_here@/:memory:")

    try:
        with pytest.raises(RuntimeError) as exc_info:
            importlib.reload(main)
        error_msg = str(exc_info.value)
        assert "super_secret_password_here" not in error_msg
        assert ":***@" in error_msg
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)
        monkeypatch.delenv("MASTERDB_DATABASE_URL", raising=False)
        importlib.reload(main)
