from fastapi.testclient import TestClient

import main
from tests.test_identity_fixtures import get_test_auth_headers

AUTH_HEADERS = get_test_auth_headers(actor="kavy", roles=["admin", "operator"])


def make_client(tmp_path):
    main.package_registry_service.store.reports_dir = tmp_path / "registry"
    main.package_registry_service.store.reports_dir.mkdir(parents=True, exist_ok=True)
    main.knowledge_object_service.store.reports_dir = tmp_path / "knowledge_objects"
    main.knowledge_object_service.store.reports_dir.mkdir(parents=True, exist_ok=True)
    main.retrieval_readiness_service.store.reports_dir = tmp_path / "retrieval_evidence"
    main.retrieval_readiness_service.store.reports_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(main.app, headers=AUTH_HEADERS)


def register_payload(dataset_id="ds-api-1"):
    return {
        "dataset_id": dataset_id,
        "dataset_version": "1.0.0",
        "schema_version": "2",
        "board": "AI",
        "medium": "text",
        "language": "en",
        "owner": "kavy",
        "actor": "pipeline",
        "reason": "Initial registration via API.",
    }


def test_register_promote_and_get_package(tmp_path):
    client = make_client(tmp_path)

    register_response = client.post("/packages/register", json=register_payload())
    assert register_response.status_code == 200
    package_id = register_response.json()["package_id"]
    assert register_response.json()["status"] == "REGISTERED"

    promote_response = client.post(
        "/packages/promote",
        json={
            "package_id": package_id,
            "to_status": "INGESTED",
            "actor": "pipeline",
            "reason": "Ingestion complete.",
        },
    )
    assert promote_response.status_code == 200
    assert promote_response.json()["status"] == "INGESTED"

    get_response = client.get(f"/packages/{package_id}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "INGESTED"


def test_illegal_promotion_returns_400(tmp_path):
    client = make_client(tmp_path)
    package_id = client.post("/packages/register", json=register_payload()).json()["package_id"]

    response = client.post(
        "/packages/promote",
        json={
            "package_id": package_id,
            "to_status": "CERTIFIED",
            "actor": "pipeline",
            "reason": "Skip ahead.",
        },
    )

    assert response.status_code == 400


def test_deprecate_package(tmp_path):
    client = make_client(tmp_path)
    package_id = client.post("/packages/register", json=register_payload()).json()["package_id"]

    response = client.post(
        "/packages/deprecate",
        json={"package_id": package_id, "actor": "owner", "reason": "Data quality issue."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "DEPRECATED"


def test_unknown_package_returns_404(tmp_path):
    client = make_client(tmp_path)

    assert client.get("/packages/unknown").status_code == 404
    assert client.get("/packages/unknown/history").status_code == 404
    assert client.get("/packages/unknown/lineage").status_code == 404
    assert client.get("/packages/unknown/retrieval").status_code == 404


def test_history_endpoint_returns_transitions(tmp_path):
    client = make_client(tmp_path)
    package_id = client.post("/packages/register", json=register_payload()).json()["package_id"]
    client.post(
        "/packages/promote",
        json={
            "package_id": package_id,
            "to_status": "INGESTED",
            "actor": "pipeline",
            "reason": "Ingestion complete.",
        },
    )

    response = client.get(f"/packages/{package_id}/history")

    assert response.status_code == 200
    to_statuses = [record["to_status"] for record in response.json()["history"]]
    assert to_statuses == ["REGISTERED", "INGESTED"]


def test_knowledge_object_and_lineage_endpoints(tmp_path):
    client = make_client(tmp_path)
    package_id = client.post("/packages/register", json=register_payload()).json()["package_id"]

    ko_response = client.post(
        f"/packages/{package_id}/knowledge-object",
        json={
            "package_id": package_id,
            "source_reference": "s3://bucket/source.csv",
            "derivation_path": ["ingest"],
        },
    )
    assert ko_response.status_code == 200
    assert ko_response.json()["package_id"] == package_id

    lineage_response = client.get(f"/packages/{package_id}/lineage")
    assert lineage_response.status_code == 200
    assert lineage_response.json()["knowledge_object_registered"] is True


def test_retrieval_endpoint_reflects_lifecycle_state(tmp_path):
    client = make_client(tmp_path)
    package_id = client.post("/packages/register", json=register_payload()).json()["package_id"]

    response = client.get(f"/packages/{package_id}/retrieval")

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_RETRIEVABLE"
