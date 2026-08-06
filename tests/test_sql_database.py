"""
Proves the real-database backend actually works — round trip through
SqlArtifactStore directly, and through both services with a SQLite file
standing in for what MASTERDB_DATABASE_URL would point at in production
(SQLite is a real SQL database; the only thing that changes for real
Postgres is the connection string SQLAlchemy is given).
"""
import shutil
import tempfile

import pytest

from bcaes_registry.models import RegisterObjectRequest, RegistryType, UpdateObjectRequest
from bcaes_registry.service import BCAESRegistryService
from bcaes_registry.store import ObjectNotFoundError
from canonical_repository.models import DocumentCategory, PublishVersionRequest, RegisterDocumentRequest
from canonical_repository.service import CanonicalRepositoryService
from services.sql_artifact_store import SqlArtifactStore


@pytest.fixture
def db_url():
    tmp_dir = tempfile.mkdtemp()
    yield f"sqlite:///{tmp_dir}/test.db"
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sql_artifact_store_save_load_round_trip(db_url):
    store = SqlArtifactStore(db_url, store_name="test")
    store.save("key-1", {"name": "X", "n": 1})
    assert store.load("key-1") == {"name": "X", "n": 1}


def test_sql_artifact_store_load_missing_returns_none(db_url):
    store = SqlArtifactStore(db_url, store_name="test")
    assert store.load("nope") is None


def test_sql_artifact_store_save_overwrites(db_url):
    store = SqlArtifactStore(db_url, store_name="test")
    store.save("key-1", {"n": 1})
    store.save("key-1", {"n": 2})
    assert store.load("key-1") == {"n": 2}


def test_sql_artifact_store_list_all_is_sorted_and_filters_prefix(db_url):
    store = SqlArtifactStore(db_url, store_name="test")
    store.save("b", {"v": "b"})
    store.save("a", {"v": "a"})
    store.save("idx-b", {"v": "index"})
    records = store.list_all(exclude_prefixes=["idx-"])
    assert records == [{"v": "a"}, {"v": "b"}]


def test_sql_artifact_store_delete(db_url):
    store = SqlArtifactStore(db_url, store_name="test")
    store.save("key-1", {"n": 1})
    assert store.delete("key-1") is True
    assert store.load("key-1") is None
    assert store.delete("key-1") is False


def test_sql_artifact_store_partitions_by_store_name(db_url):
    """Two logical stores sharing one database/table must not see each
    other's keys — this is what lets bcaes_registry and
    canonical_repository share one MASTERDB_DATABASE_URL safely."""
    store_a = SqlArtifactStore(db_url, store_name="a")
    store_b = SqlArtifactStore(db_url, store_name="b")
    store_a.save("shared-key", {"owner": "a"})
    store_b.save("shared-key", {"owner": "b"})
    assert store_a.load("shared-key") == {"owner": "a"}
    assert store_b.load("shared-key") == {"owner": "b"}
    assert len(store_a.list_all()) == 1


def test_bcaes_registry_persists_via_real_sql_database_across_fresh_instance(db_url):
    store = SqlArtifactStore(db_url, store_name="bcaes_registry")
    service_a = BCAESRegistryService(artifact_store=store)
    obj = service_a.register(
        RegistryType.CAPABILITY,
        RegisterObjectRequest(name="Schema Validation", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )

    # Fresh service instance, fresh SqlArtifactStore, same db_url — the
    # actual shape of "the process restarted, MASTERDB_DATABASE_URL is
    # still the same Postgres connection string."
    store_b = SqlArtifactStore(db_url, store_name="bcaes_registry")
    service_b = BCAESRegistryService(artifact_store=store_b)
    reloaded = service_b.get(RegistryType.CAPABILITY, obj.id)
    assert reloaded.name == "Schema Validation"


def test_bcaes_registry_update_and_delete_persist_via_sql(db_url):
    store = SqlArtifactStore(db_url, store_name="bcaes_registry")
    service_a = BCAESRegistryService(artifact_store=store)
    obj = service_a.register(
        RegistryType.ENGINE,
        RegisterObjectRequest(name="Scoring Engine", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )
    service_a.update(RegistryType.ENGINE, obj.id, UpdateObjectRequest(version="2.0"))

    store_b = SqlArtifactStore(db_url, store_name="bcaes_registry")
    service_b = BCAESRegistryService(artifact_store=store_b)
    assert service_b.get(RegistryType.ENGINE, obj.id).version == "2.0"

    service_b.delete(RegistryType.ENGINE, obj.id)
    store_c = SqlArtifactStore(db_url, store_name="bcaes_registry")
    service_c = BCAESRegistryService(artifact_store=store_c)
    with pytest.raises(ObjectNotFoundError):
        service_c.get(RegistryType.ENGINE, obj.id)


def test_canonical_repository_persists_via_real_sql_database(db_url):
    store = SqlArtifactStore(db_url, store_name="canonical_repository")
    service_a = CanonicalRepositoryService(artifact_store=store)
    doc = service_a.register(
        RegisterDocumentRequest(category=DocumentCategory.BCAES_VOL_4, title="Vol 4", owner="Kavy"),
        actor="Kavy",
        actor_roles=["bcaes-editor"],
    )
    service_a.publish_version(
        doc.id,
        PublishVersionRequest(content="real content", change_note="n", published_by="Kavy"),
        actor="Kavy",
        actor_roles=["bcaes-editor"],
    )

    store_b = SqlArtifactStore(db_url, store_name="canonical_repository")
    service_b = CanonicalRepositoryService(artifact_store=store_b)
    reloaded = service_b.get(doc.id, actor="Kavy", actor_roles=["ecosystem-reader"])
    assert reloaded.current_version == 2
    latest = service_b.latest_version(doc.id, actor="Kavy", actor_roles=["ecosystem-reader"])
    assert latest.content == "real content"


def test_bcaes_registry_and_canonical_repository_can_share_one_database_url(db_url):
    """The actual production shape: one MASTERDB_DATABASE_URL, both
    services pointed at it with different store_names."""
    bcaes_store = SqlArtifactStore(db_url, store_name="bcaes_registry")
    doc_store = SqlArtifactStore(db_url, store_name="canonical_repository")
    bcaes_service = BCAESRegistryService(artifact_store=bcaes_store)
    doc_service = CanonicalRepositoryService(artifact_store=doc_store)

    bcaes_service.register(
        RegistryType.DOMAIN,
        RegisterObjectRequest(name="Ingestion Domain", purpose="p", owner="Kavy", authority_boundaries=["Kavy"]),
    )
    doc_service.register(
        RegisterDocumentRequest(category=DocumentCategory.BCAB, title="BCAB", owner="Kavy"),
        actor="Kavy",
        actor_roles=["bcaes-editor"],
    )

    assert len(bcaes_service.list_registry(RegistryType.DOMAIN)) == 1
    assert len(doc_service.list_all(actor="Kavy", actor_roles=["ecosystem-reader"])) == 1
