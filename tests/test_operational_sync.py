import pytest
from fastapi.testclient import TestClient

import main
from operational_sync.service import NiyantranSyncService, ParikshakSyncService


@pytest.fixture(autouse=True)
def _fresh_sync_services():
    main.parikshak_sync_service = ParikshakSyncService()
    main.niyantran_sync_service = NiyantranSyncService()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _auth(actor="Kavy", roles=None):
    token, _ = main.auth_service.issue_token(actor, roles or [])
    return {"Authorization": f"Bearer {token}"}


# --- PARIKSHAK -----------------------------------------------------------


def test_upsert_review_reference_requires_sync_role(client):
    resp = client.post(
        "/parikshak/review-references",
        json={"external_review_id": "rev-1", "subject": "x", "summary": "s",
              "readiness_status": "ready", "source_url": None},
        headers=_auth(roles=["some-other-role"]),
    )
    assert resp.status_code == 403


def test_upsert_review_reference_requires_token_at_all(client):
    resp = client.post(
        "/parikshak/review-references",
        json={"external_review_id": "rev-1", "subject": "x", "summary": "s",
              "readiness_status": "ready", "source_url": None},
    )
    assert resp.status_code == 401


def test_upsert_review_reference_succeeds_with_sync_role(client):
    resp = client.post(
        "/parikshak/review-references",
        json={"external_review_id": "rev-1", "subject": "bcaes-cap-1", "summary": "Looks good.",
              "readiness_status": "ready", "source_url": "https://parikshak.internal/rev-1"},
        headers=_auth(roles=["parikshak-sync"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["readiness_status"] == "ready"
    assert body["subject"] == "bcaes-cap-1"


def test_upsert_review_reference_succeeds_with_admin_role(client):
    resp = client.post(
        "/parikshak/review-references",
        json={"external_review_id": "rev-1", "subject": "x", "summary": "s",
              "readiness_status": "not_ready", "source_url": None},
        headers=_auth(roles=["bhiv-admin"]),
    )
    assert resp.status_code == 200


def test_upsert_is_idempotent_by_external_id(client):
    body = {"external_review_id": "rev-1", "subject": "x", "summary": "first",
            "readiness_status": "in_review", "source_url": None}
    client.post("/parikshak/review-references", json=body, headers=_auth(roles=["parikshak-sync"]))
    body["summary"] = "updated"
    body["readiness_status"] = "ready"
    client.post("/parikshak/review-references", json=body, headers=_auth(roles=["parikshak-sync"]))

    resp = client.get("/parikshak/review-references/rev-1")
    assert resp.json()["summary"] == "updated"
    assert resp.json()["readiness_status"] == "ready"

    all_resp = client.get("/parikshak/review-references")
    assert all_resp.json()["count"] == 1


def test_get_missing_review_reference_404(client):
    resp = client.get("/parikshak/review-references/does-not-exist")
    assert resp.status_code == 404


def test_list_review_references_is_public_read(client):
    client.post(
        "/parikshak/review-references",
        json={"external_review_id": "rev-1", "subject": "x", "summary": "s",
              "readiness_status": "ready", "source_url": None},
        headers=_auth(roles=["parikshak-sync"]),
    )
    resp = client.get("/parikshak/review-references")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_summary_field_is_length_capped():
    """Structural enforcement of 'do not duplicate engineering
    intelligence' — the model itself won't accept a full review dump."""
    from pydantic import ValidationError
    from operational_sync.models import UpsertReviewReferenceRequest

    with pytest.raises(ValidationError):
        UpsertReviewReferenceRequest(
            external_review_id="rev-1", subject="x", summary="x" * 501,
            readiness_status="ready", source_url=None,
        )


# --- NIYANTRAN -------------------------------------------------------------


def test_upsert_task_state_requires_sync_role(client):
    resp = client.post(
        "/niyantran/task-state",
        json={"external_task_id": "task-1", "candidate": "Kavy", "progress": 10, "status": "assigned"},
        headers=_auth(roles=["irrelevant"]),
    )
    assert resp.status_code == 403


def test_upsert_task_state_succeeds_with_sync_role(client):
    resp = client.post(
        "/niyantran/task-state",
        json={"external_task_id": "task-1", "candidate": "Kavy", "progress": 25, "status": "in_progress"},
        headers=_auth(roles=["niyantran-sync"]),
    )
    assert resp.status_code == 200
    assert resp.json()["progress"] == 25


def test_task_state_progress_is_bounded_0_to_100():
    from pydantic import ValidationError
    from operational_sync.models import UpsertOperationalTaskStateRequest

    with pytest.raises(ValidationError):
        UpsertOperationalTaskStateRequest(
            external_task_id="task-1", candidate="Kavy", progress=150, status="in_progress"
        )


def test_task_state_upsert_is_idempotent_by_external_id(client):
    body = {"external_task_id": "task-1", "candidate": "Kavy", "progress": 10, "status": "assigned"}
    client.post("/niyantran/task-state", json=body, headers=_auth(roles=["niyantran-sync"]))
    body["progress"] = 90
    body["status"] = "complete"
    client.post("/niyantran/task-state", json=body, headers=_auth(roles=["niyantran-sync"]))

    resp = client.get("/niyantran/task-state/task-1")
    assert resp.json()["progress"] == 90
    assert resp.json()["status"] == "complete"
    assert client.get("/niyantran/task-state").json()["count"] == 1


def test_get_missing_task_state_404(client):
    resp = client.get("/niyantran/task-state/does-not-exist")
    assert resp.status_code == 404


def test_niyantran_store_has_no_execution_side_effects(client):
    """'MASTERDB records operational truth only and must not execute
    workflow' — pinning down that marking a task complete here has zero
    effect on anything else in the app (no other registry/store changes)."""
    before = main.bcaes_registry_service.registry_summary()
    client.post(
        "/niyantran/task-state",
        json={"external_task_id": "task-1", "candidate": "Kavy", "progress": 100, "status": "complete"},
        headers=_auth(roles=["niyantran-sync"]),
    )
    after = main.bcaes_registry_service.registry_summary()
    assert before == after
