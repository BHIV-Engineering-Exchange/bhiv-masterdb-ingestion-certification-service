from tests.test_identity_fixtures import get_test_auth_headers
AUTH_HEADERS = get_test_auth_headers(actor="admin", roles=["admin", "operator"])
from pathlib import Path

from fastapi.testclient import TestClient

import main


ROOT = Path(__file__).resolve().parents[1]


def test_validate_certify_status_and_report_api(tmp_path):
    main.artifact_store.reports_dir = tmp_path
    client = TestClient(main.app, headers=AUTH_HEADERS)

    payload = {
        "dataset_id": "api-certifiable",
        "dataset_path": str(ROOT / "datasets" / "certifiable_sample.csv"),
        "metadata_path": str(ROOT / "datasets" / "metadata.json"),
    }
    validate_response = client.post("/validate", json=payload)
    assert validate_response.status_code == 200
    assert validate_response.json()["state"] == "VALIDATED"

    certify_response = client.post("/certify", json={"dataset_id": "api-certifiable"})
    assert certify_response.status_code == 200
    assert certify_response.json()["decision"]["eligible_for_masterdb"] is True

    status_response = client.get("/status/api-certifiable")
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "CERTIFIED"

    report_response = client.get("/report/api-certifiable")
    assert report_response.status_code == 200
    assert report_response.json()["dataset_id"] == "api-certifiable"


def test_unknown_dataset_returns_404(tmp_path):
    main.artifact_store.reports_dir = tmp_path
    client = TestClient(main.app, headers=AUTH_HEADERS)

    response = client.get("/status/unknown")

    assert response.status_code == 404

