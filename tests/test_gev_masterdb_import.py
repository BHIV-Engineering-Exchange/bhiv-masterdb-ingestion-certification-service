import json

import pytest
from fastapi.testclient import TestClient

import main
from geo_quest_candidate.masterdb_import import (
    CandidatePackageRetrieveRequest,
    CandidateUseDeniedError,
    GeospatialExportCandidateService,
)
from geo_quest_candidate.service import CandidateRegistrationError
from services.artifact_store import ArtifactStore


client = TestClient(main.app)
PACKET_ID = "gev-geospatial-masterdb-intake"
DATASET_ID = "forest-data-gap"
RECORD_ID = "TBD-MASTERDB-FOREST-DATA-GAP"


def _write_packet(root, *, invalid_schema=False, provenance_mismatch=False, invalid_license=False):
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    artifact = {
        "dataset": DATASET_ID,
        "status": "unavailable",
        "feature_count": 0,
        "features": [],
        "is_dataset": False,
        "required_before_submission": ["identify an authoritative source"],
    }
    (data_dir / "forest_data_status.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )
    dataset_format = "JSON availability status; not a geospatial dataset"
    record = {
        "capabilityId": RECORD_ID,
        "capabilityName": "Forest data availability status",
        "classification": {"source": "Different source" if provenance_mismatch else "Not identified"},
        "purpose": "Record the absence of forest data",
        "source": "Different source" if provenance_mismatch else "Not identified",
        "datasets": [{"file": "data/forest_data_status.json", "format": dataset_format}],
        "authorityCustodian": "Unknown",
        "input": [],
        "output": [],
        "dependencies": [],
        "spatialCoverage": "Not available",
        "temporalCoverage": "Not available",
        "schema": {
            "is_dataset": False,
            "feature_count": 1 if invalid_schema else 0,
            "features": [],
        },
        "apiInterface": {},
        "license": "Not applicable until source is identified",
        "attribution": "Not applicable",
        "provenance": {},
        "validationStatus": "review required",
        "qualityStatus": "no data",
        "knownLimitations": ["No forest/woodland geometry is supplied"],
        "potentialConsumers": [],
        "bharatMalaRelevance": "None without sourced data",
        "vanaFinRelevance": "Potential future relevance",
        "masterdbRegistrationStatus": "candidate",
        "nextRequiredAction": "Identify source and license",
        "evidenceLocation": "data/forest_data_status.json",
    }
    manifest_entry = {
        "datasetId": DATASET_ID,
        "registryRecordId": RECORD_ID,
        "file": "data/forest_data_status.json",
        "format": "JSON availability status (not geospatial features)",
        "recordCount": 0,
        "license": "CC BY-NC 4.0" if invalid_license else None,
    }
    if provenance_mismatch:
        manifest_entry["sourceUrl"] = "https://example.invalid/source"
    document = {"records": [record]}
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "packetId": PACKET_ID,
                "packetVersion": 1,
                "datasets": [manifest_entry],
            }
        ),
        encoding="utf-8",
    )
    (root / "registry_records.json").write_text(json.dumps(document), encoding="utf-8")
    (data_dir / "dataset_records.json").write_text(json.dumps(document), encoding="utf-8")


def _service(tmp_path, *, invalid_schema=False, provenance_mismatch=False, invalid_license=False):
    import_dir = tmp_path / "export"
    _write_packet(
        import_dir,
        invalid_schema=invalid_schema,
        provenance_mismatch=provenance_mismatch,
        invalid_license=invalid_license,
    )
    return GeospatialExportCandidateService(
        store=ArtifactStore(str(tmp_path / "candidate-store")),
        import_dir=import_dir,
    )


def _token(actor, roles):
    response = client.post("/auth/token", json={"actor": actor, "roles": roles})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_valid_export_stages_noncanonical_candidate_and_is_not_discoverable(tmp_path, monkeypatch):
    service = _service(tmp_path)
    monkeypatch.setattr(main, "gev_geospatial_candidate_service", service)
    headers = {"Authorization": f"Bearer {_token('admin', ['bhiv-admin'])}"}

    response = client.post("/geo-quest/imports/register", headers=headers)
    assert response.status_code == 202
    assert response.json()["registration_status"] == "PENDING_AUTHORIZATION"
    assert response.json()["canonical"] is False
    assert response.json()["discoverable"] is False
    assert response.json()["mdu_contract_validation"]["status"] == "PENDING"

    details = client.get("/geo-quest/imports/candidate", headers=headers)
    assert details.status_code == 200
    assert details.json()["candidate_record_count"] == 1

    retrieved = client.post(
        "/geo-quest/imports/candidate/retrieve",
        json={"dataset_id": DATASET_ID, "purpose": "registry_review"},
        headers=headers,
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["canonical"] is False
    assert retrieved.json()["data"]["feature_count"] == 0

    discovery = client.get("/capabilities?search=FOREST-DATA-GAP", headers=headers)
    assert discovery.status_code == 200
    assert all(item.get("capability_id") != RECORD_ID for item in discovery.json())


@pytest.mark.parametrize(
    "invalid_schema,provenance_mismatch,invalid_license",
    [(True, False, False), (False, True, False), (False, False, True)],
)
def test_invalid_schema_provenance_and_license_are_rejected(
    tmp_path, invalid_schema, provenance_mismatch, invalid_license
):
    service = _service(
        tmp_path,
        invalid_schema=invalid_schema,
        provenance_mismatch=provenance_mismatch,
        invalid_license=invalid_license,
    )
    with pytest.raises(CandidateRegistrationError):
        service.register_candidate("reviewer")


def test_candidate_retrieval_rejects_unapproved_use_and_detects_tampering(tmp_path):
    service = _service(tmp_path)
    service.register_candidate("reviewer")

    with pytest.raises(CandidateUseDeniedError):
        service.retrieve(CandidatePackageRetrieveRequest(dataset_id=DATASET_ID, purpose="production"))

    bundle = service.store.load(PACKET_ID)
    bundle["artifacts"]["data/forest_data_status.json"]["content"] += " "
    service.store.save(PACKET_ID, bundle)
    with pytest.raises(CandidateRegistrationError):
        service.get_candidate()


def test_registration_refuses_metadata_changes_after_staging(tmp_path):
    service = _service(tmp_path)
    service.register_candidate("reviewer")
    manifest_path = service.import_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["review_note"] = "changed after staging"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CandidateRegistrationError, match="differs from the already staged packet"):
        service.register_candidate("reviewer")


def test_gev_candidate_routes_require_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "gev_geospatial_candidate_service", _service(tmp_path))
    headers = {
        "Authorization": f"Bearer {_token('gev-viewer', ['ecosystem-reader'])}"
    }

    assert client.post("/geo-quest/imports/register", headers=headers).status_code == 403
    assert client.get("/geo-quest/imports/candidate", headers=headers).status_code == 403
    assert client.post(
        "/geo-quest/imports/candidate/retrieve",
        json={"dataset_id": DATASET_ID},
        headers=headers,
    ).status_code == 403
