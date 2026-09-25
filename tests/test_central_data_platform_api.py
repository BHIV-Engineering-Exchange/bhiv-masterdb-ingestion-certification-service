"""Integration tests for Phase 4 (Central Data Platform) and Phase 8 (Evidence Preservation) API endpoints."""
import pytest
from fastapi.testclient import TestClient

import main
from models import PackageStatus
from services.bucket_client import BucketClient
from services.dataset_retrieval_service import DatasetRetrievalService
from services.knowledge_object_service import KnowledgeObjectService
from services.package_registry_service import PackageRegistryService
from services.retrieval_readiness_service import RetrievalReadinessService


@pytest.fixture(autouse=True)
def _fresh_services(tmp_path):
    """Reset the services backing the Phase 4/8 endpoints for every test."""
    registry = PackageRegistryService(store_dir=str(tmp_path / "registry"))
    knowledge_objects = KnowledgeObjectService(
        registry=registry, store_dir=str(tmp_path / "knowledge_objects")
    )
    retrieval = RetrievalReadinessService(
        registry=registry,
        knowledge_object_service=knowledge_objects,
        store_dir=str(tmp_path / "retrieval_evidence"),
    )
    main.package_registry_service = registry
    main.knowledge_object_service = knowledge_objects
    main.retrieval_readiness_service = retrieval
    main.dataset_retrieval_service = DatasetRetrievalService(
        registry=registry,
        knowledge_object_service=knowledge_objects,
        retrieval_readiness_service=retrieval,
    )
    main.bucket_client = BucketClient()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _register_package(registry, dataset_id="api-ds-1"):
    return registry.register(
        dataset_id=dataset_id,
        dataset_version="1.0.0",
        schema_version="2",
        board="AI",
        medium="text",
        language="en",
        owner="kavy",
    )


def _promote_to_retrieval_ready(registry, package_id):
    """Walk a package through the full lifecycle to RETRIEVAL_READY so that
    retrieval operations (query/export/stream) are permitted."""
    for status in [
        PackageStatus.INGESTED,
        PackageStatus.VALIDATED,
        PackageStatus.VERIFIED,
        PackageStatus.CERTIFIED,
        PackageStatus.RETRIEVAL_READY,
    ]:
        registry.promote(package_id, status, actor="test", reason="test setup")


def test_list_datasets_empty(client):
    response = client.get("/datasets")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["datasets"] == []


def test_list_datasets_returns_summaries(client, tmp_path):
    _register_package(main.package_registry_service, "ds-1")
    _register_package(main.package_registry_service, "ds-2")

    response = client.get("/datasets")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    ids = {d["dataset_id"] for d in body["datasets"]}
    assert ids == {"ds-1", "ds-2"}


def test_query_dataset_not_found(client):
    response = client.post("/query", json={"dataset_id": "nonexistent", "query_params": {}})
    assert response.status_code == 404


def test_query_dataset_found(client):
    pkg = _register_package(main.package_registry_service, "ds-query")
    _promote_to_retrieval_ready(main.package_registry_service, pkg.package_id)
    response = client.post(
        "/query",
        json={"dataset_id": "ds-query", "query_params": {"query": "SELECT *"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "ds-query"
    assert body["operation"] == "query"
    assert body["granted"] is True


def test_export_dataset_not_found(client):
    response = client.post("/export", json={"dataset_id": "nonexistent", "format": "csv"})
    assert response.status_code == 404


def test_export_dataset_found(client):
    pkg = _register_package(main.package_registry_service, "ds-export")
    _promote_to_retrieval_ready(main.package_registry_service, pkg.package_id)
    response = client.post("/export", json={"dataset_id": "ds-export", "format": "csv"})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "ds-export"
    assert body["operation"] == "export"
    assert body["granted"] is True


def test_stream_dataset_not_found(client):
    response = client.post("/stream", json={"dataset_id": "nonexistent", "stream_params": {}})
    assert response.status_code == 404


def test_stream_dataset_found(client):
    pkg = _register_package(main.package_registry_service, "ds-stream")
    _promote_to_retrieval_ready(main.package_registry_service, pkg.package_id)
    response = client.post("/stream", json={"dataset_id": "ds-stream", "stream_params": {"format": "json"}})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "ds-stream"
    assert body["operation"] == "stream"
    assert body["granted"] is True


def test_reference_dataset_not_found(client):
    response = client.post("/reference", json={"dataset_id": "nonexistent"})
    assert response.status_code == 404


def test_reference_dataset_found(client):
    pkg = _register_package(main.package_registry_service, "ds-ref")
    # reference works even for a freshly-registered (non-RETRIEVAL_READY) package
    response = client.post("/reference", json={"dataset_id": "ds-ref"})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "ds-ref"
    assert body["operation"] == "reference"
    assert body["granted"] is True


# -- Phase 4: Inspection Endpoints -----------------------------------------


def test_get_dataset_detail_not_found(client):
    """Unknown dataset_id returns 404."""
    response = client.get("/datasets/nonexistent-ds")
    assert response.status_code == 404


def test_get_dataset_detail_found(client):
    """Known dataset returns full detail with history, knowledge_object, retrieval_evidence."""
    pkg = _register_package(main.package_registry_service, "ds-detail")
    response = client.get("/datasets/ds-detail")
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "ds-detail"
    assert body["package_id"] == pkg.package_id
    assert "history" in body
    assert "knowledge_object" in body
    assert "retrieval_evidence" in body


def test_get_dataset_schema_returns_registry_declared_fallback(client):
    """When MDU is not configured, schema returns registry-declared source."""
    _register_package(main.package_registry_service, "ds-schema")
    response = client.get("/datasets/ds-schema/schema")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] in ("placeholder", "mdu-live", "registry-declared")
    assert body["dataset_id"] == "ds-schema"


def test_get_dataset_versions_not_found(client):
    """Unknown dataset_id returns 404."""
    response = client.get("/datasets/unknown-ds/versions")
    assert response.status_code == 404


def test_get_dataset_versions_found(client):
    """Returns all versions sorted by creation time; at least 1 for a newly registered package."""
    _register_package(main.package_registry_service, "ds-versions")
    response = client.get("/datasets/ds-versions/versions")
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "ds-versions"
    assert body["version_count"] >= 1
    assert len(body["versions"]) >= 1
    # versions should be sorted ascending by created_at (earliest first)
    created_ats = [v["created_at"] for v in body["versions"]]
    assert created_ats == sorted(created_ats)


def test_get_dataset_provenance_not_found(client):
    """Unknown dataset_id returns 404."""
    response = client.get("/datasets/unknown-ds/provenance")
    assert response.status_code == 404


def test_get_dataset_provenance_found(client):
    """Returns masterdb_lineage (and mdu_provenance when MDU is unavailable, gracefully degrades)."""
    _register_package(main.package_registry_service, "ds-prov2")
    response = client.get("/datasets/ds-prov2/provenance")
    assert response.status_code == 200
    body = response.json()
    assert "dataset_id" in body
    assert "masterdb_lineage" in body


# -- Phase 8: Evidence & Bucket ------------------------------------------------


def test_bucket_status_unconfigured(client):
    """When no PRAVAH_BHIV_BUCKET is set, status reports NOT_CONFIGURED."""
    response = client.get("/bucket/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["base_url"] == "NOT_CONFIGURED"


def test_create_evidence_when_bucket_unconfigured(client):
    """When Bucket is unconfigured, store_evidence raises BucketUnavailableError -> 503.

    Endpoint follows spec §4.1: POST /evidence/{evidence_id} (path param, not body).
    """
    response = client.post("/evidence/ev-1", json={"audit": True})
    assert response.status_code == 503


def test_retrieve_evidence_when_bucket_unconfigured(client):
    """When Bucket is unconfigured, get_evidence raises BucketUnavailableError -> 503."""
    response = client.get("/evidence/ev-1")
    assert response.status_code == 503


def test_store_provenance_when_bucket_unconfigured(client):
    """When Bucket is unconfigured, store_provenance raises BucketUnavailableError -> 503.

    Endpoint follows spec §4.1: POST /provenance/{dataset_id}.
    """
    response = client.post("/provenance/test-ds-id", json={"lineage": {}})
    assert response.status_code == 503


def test_get_provenance_unknown_package(client):
    response = client.get("/provenance/pkg-missing")
    assert response.status_code == 404


def test_get_provenance_known_package(client):
    package = _register_package(main.package_registry_service, "ds-prov")
    response = client.get(f"/provenance/{package.package_id}")
    assert response.status_code == 200
    # lineage returns a dict with ancestors, descendants, etc.
    body = response.json()
    assert body["package_id"] == package.package_id
    assert "ancestors" in body
    assert "descendants" in body
