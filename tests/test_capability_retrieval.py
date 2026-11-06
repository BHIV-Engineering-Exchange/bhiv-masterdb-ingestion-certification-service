from tests.test_identity_fixtures import get_test_token
"""
Tests for Governed Capability Data Retrieval & Provenance.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import main
from main import app
from services.artifact_store import ArtifactStore
from services.earthquake_observation_service import EarthquakeObservationService

client = TestClient(app)


def _get_token(actor="retrieval-tester", roles=None):
    return get_test_token(actor=actor, roles=roles)


def test_retrieve_capability_data_success():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    
    # 1. Request access
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()

    # 2. Retrieve data using access_token grant
    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
            "query_params": {"region": "Sundarbans-North"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 200
    data = ret_res.json()
    assert "data" in data
    assert data["capability"]["capability_id"] == "cap-mangrove-monitoring"
    assert data["capability"]["domain"] == "geospatial"
    assert "provenance" in data
    assert "request_id" in data
    assert data["data"]["region"] == "Sundarbans-North"

    # 3. Verify audit record
    req_id = grant["request_id"]
    audit_res = client.get(f"/access/{req_id}", headers={"Authorization": f"Bearer {token}"})
    assert audit_res.status_code == 200
    audit_contract = audit_res.json()
    assert audit_contract["request_id"] == req_id
    assert audit_contract["authorized"] is True


def test_earthquake_retrieval_returns_filtered_seismic_observations(tmp_path, monkeypatch):
    observations = EarthquakeObservationService(ArtifactStore(str(tmp_path / "earthquakes")))
    now = datetime.now(timezone.utc)
    observations.ingest({
        "source": "USGS",
        "observations": [
            {
                "event_id": "us-test-recent-strong",
                "source": "USGS",
                "place": "Recent event",
                "magnitude": 3.2,
                "longitude": 151.2,
                "latitude": -33.8,
                "depth_km": 12.0,
                "event_time_utc": now.isoformat(),
                "source_url": "https://earthquake.usgs.gov/test/recent",
            },
            {
                "event_id": "us-test-recent-weak",
                "source": "USGS",
                "place": "Recent weak event",
                "magnitude": 2.0,
                "longitude": 151.2,
                "latitude": -33.8,
                "depth_km": 12.0,
                "event_time_utc": now.isoformat(),
                "source_url": "https://earthquake.usgs.gov/test/weak",
            },
            {
                "event_id": "us-test-old-strong",
                "source": "USGS",
                "place": "Older event",
                "magnitude": 4.0,
                "longitude": 151.2,
                "latitude": -33.8,
                "depth_km": 12.0,
                "event_time_utc": (now - timedelta(days=2)).isoformat(),
                "source_url": "https://earthquake.usgs.gov/test/old",
            },
        ],
    })
    monkeypatch.setattr(main.capability_registry_service, "earthquake_observation_service", observations)
    monkeypatch.setenv("AUTH_ENTITLED_APPS_EARTHQUAKE_TEST_CONSUMER", "EARTHQUAKE_TEST_CONSUMER")
    capability = main.capability_registry_service.get_capability("cap-gev-earthquake-monitoring")
    assert capability.dataset_id == "ds-gev-seismic-events"

    token = _get_token(actor="EARTHQUAKE_TEST_CONSUMER", roles=["ecosystem-reader"])
    grant_response = client.post(
        "/access/request",
        json={
            "application_id": "EARTHQUAKE_TEST_CONSUMER",
            "capability_id": "cap-gev-earthquake-monitoring",
            "purpose": "seismic_hazard_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert grant_response.status_code == 200

    response = client.post(
        "/capabilities/cap-gev-earthquake-monitoring/retrieve",
        json={
            "application_id": "EARTHQUAKE_TEST_CONSUMER",
            "access_token": grant_response.json()["access_token"],
            "query_params": {"min_magnitude": 2.5, "time_window": "24h"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["capability"]["dataset_id"] == "ds-gev-seismic-events"
    assert result["data"]["dataset_id"] == "ds-gev-seismic-events"
    assert result["data"]["count"] == 1
    assert result["data"]["returned_count"] == 1
    assert [item["event_id"] for item in result["data"]["observations"]] == ["us-test-recent-strong"]
    assert result["data"]["observations"][0]["source"] == "USGS"
    assert "canopy_density_pct" not in result["data"]
    assert result["provenance"]["is_synthetic"] is False
    assert result["provenance"]["content_digest_sha256"] == result["content_digest_sha256"]
    assert len(result["content_digest_sha256"]) == 64
    assert "mdu_provenance" in result["provenance"]
    invalid_response = client.post(
        "/capabilities/cap-gev-earthquake-monitoring/retrieve",
        json={
            "application_id": "EARTHQUAKE_TEST_CONSUMER",
            "access_token": grant_response.json()["access_token"],
            "query_params": {"min_magnitude": "not-a-number"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invalid_response.status_code == 422
    invalid_window_response = client.post(
        "/tantra/capabilities/cap-gev-earthquake-monitoring/retrieve",
        json={
            "application_id": "EARTHQUAKE_TEST_CONSUMER",
            "access_token": grant_response.json()["access_token"],
            "query_params": {"time_window": "last day"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert invalid_window_response.status_code == 422


def test_earthquake_filters_windows_limits_and_invalid_magnitudes(tmp_path, monkeypatch):
    observations = EarthquakeObservationService(ArtifactStore(str(tmp_path / "earthquakes-query")))
    now = datetime.now(timezone.utc)
    observations.ingest({
        "source": "USGS",
        "observations": [
            {
                "event_id": f"query-{days}-{magnitude}", "source": "USGS", "place": "Fixture",
                "magnitude": magnitude, "longitude": 10.0, "latitude": 20.0, "depth_km": 5.0,
                "event_time_utc": (now - timedelta(days=days)).isoformat(),
                "source_url": "https://earthquake.usgs.gov/test/query",
            }
            for days, magnitude in ((0, 2.0), (0.5, 4.0), (8, 6.0))
        ],
    })
    monkeypatch.setattr(main.capability_registry_service, "earthquake_observation_service", observations)
    query = main.capability_registry_service._get_earthquake_payload

    assert query({"min_magnitude": 3, "max_magnitude": 5, "time_window": "24h"})["returned_count"] == 1
    assert query({"time_window": "7d", "limit": 100})["returned_count"] == 2
    assert query({"limit": "all"})["returned_count"] == 3
    assert query({"limit": None})["returned_count"] == 3
    assert query({"limit": 100})["returned_count"] == 3
    assert query({"min_magnitude": 5, "limit": 1})["count"] == 1
    assert query({"min_magnitude": 2.5, "limit": 1})["returned_count"] == 1

    for params in ({"min_magnitude": "bad"}, {"min_magnitude": 11}, {"max_magnitude": -3}, {"min_magnitude": 5, "max_magnitude": 2}):
        try:
            query(params)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid magnitude query should fail: {params}")


def test_access_grant_cannot_be_reused_for_another_capability_or_application():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    headers = {"Authorization": f"Bearer {token}"}
    grant_response = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers=headers,
    )
    assert grant_response.status_code == 200
    grant = grant_response.json()

    wrong_capability = client.post(
        "/capabilities/cap-maritime-cargo/retrieve",
        json={"application_id": "DATA_CONSUMER", "access_token": grant["access_token"]},
        headers=headers,
    )
    assert wrong_capability.status_code == 403

    wrong_application = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={"application_id": "OTHER_APPLICATION", "access_token": grant["access_token"]},
        headers=headers,
    )
    assert wrong_application.status_code == 403


def test_access_grant_cannot_be_reused_by_another_authenticated_actor():
    owner_token = _get_token(actor="grant-owner", roles=["ecosystem-reader"])
    other_actor_token = _get_token(actor="other-actor", roles=["ecosystem-reader"])
    grant_response = client.post(
        "/access/request",
        json={
            "application_id": "SHARED_CONSUMER_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert grant_response.status_code == 200
    grant = grant_response.json()

    for credential in (
        {"access_token": grant["access_token"]},
        {"request_id": grant["request_id"]},
    ):
        response = client.post(
            "/capabilities/cap-mangrove-monitoring/retrieve",
            json={"application_id": "SHARED_CONSUMER_APP", **credential},
            headers={"Authorization": f"Bearer {other_actor_token}"},
        )
        assert response.status_code == 403


def test_revoked_access_grant_denies_retrieval():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()

    # Revoke grant via DELETE /access/{request_id}
    del_res = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "revoked"

    # Attempt retrieval with revoked token -> must be rejected with 403
    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 403
    assert "revoked" in ret_res.text.lower()


def test_retrieval_trace_and_execution_correlation():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    grant = req_res.json()

    test_trace_id = "trace-tantra-cross-service-001"
    test_exec_id = "exec-tantra-cross-service-001"

    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
            "trace_id": test_trace_id,
            "execution_id": test_exec_id,
            "query_params": {"region": "Sundarbans-North"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 200
    payload = ret_res.json()
    assert payload["trace_id"] == test_trace_id
    assert payload["execution_id"] == test_exec_id
    assert "content_digest_sha256" in payload["provenance"]


def test_expired_access_grant_denies_retrieval():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()

    from main import capability_registry_service
    contract = capability_registry_service.get_access_contract(grant["access_token"])
    contract.expires_at = "2020-01-01T00:00:00+00:00"

    ret_res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ret_res.status_code == 403
    assert "expired" in ret_res.text.lower()


def test_repeated_revoke_behavior():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    grant = req_res.json()

    # First revocation succeeds
    del1 = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {token}"})
    assert del1.status_code == 200

    # Second revocation returns 404 (grant not found or already revoked)
    del2 = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {token}"})
    assert del2.status_code == 404


def test_unauthorized_actor_cannot_revoke_grant():
    owner_token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()

    # Another non-admin actor attempts to revoke
    attacker_token = _get_token(actor="ATTACKER_CONSUMER", roles=["ecosystem-reader"])
    del_res = client.delete(f"/access/{grant['request_id']}", headers={"Authorization": f"Bearer {attacker_token}"})
    assert del_res.status_code == 403
    assert "Only bhiv-admin or the grant owner" in del_res.json()["error"]["message"]


def test_access_contract_audit_redacts_token_and_enforces_auth():
    owner_token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()
    req_id = grant["request_id"]

    # 1. Owner can audit contract -> access_token must be redacted
    audit_res = client.get(f"/access/{req_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert audit_res.status_code == 200
    audit_contract = audit_res.json()
    assert audit_contract["request_id"] == req_id
    assert audit_contract["access_token"] == "[REDACTED]"

    # 2. Unauthorized actor gets 403 Forbidden
    attacker_token = _get_token(actor="ATTACKER_CONSUMER", roles=["ecosystem-reader"])
    unauth_res = client.get(f"/access/{req_id}", headers={"Authorization": f"Bearer {attacker_token}"})
    assert unauth_res.status_code == 403
    assert "Only bhiv-admin or the grant owner" in unauth_res.json()["error"]["message"]


def test_revocation_persistence_failure_fails_closed(monkeypatch):
    owner_token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert req_res.status_code == 200
    grant = req_res.json()
    req_id = grant["request_id"]

    from main import capability_registry_service

    # Simulate grant store failure during revocation
    def failing_save(*args, **kwargs):
        raise IOError("Disk quota exceeded or database connection dropped")

    if capability_registry_service.grant_store:
        monkeypatch.setattr(capability_registry_service.grant_store, "save", failing_save)

    del_res = client.delete(f"/access/{req_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert del_res.status_code == 500
    assert "Failed to persist access contract revocation" in del_res.json()["error"]["message"]


# =============================================================================
# D2: Explicit Valid Grants Only (No Implicit Grant Creation) Regression Suite
# =============================================================================

def test_d2_tokenless_retrieval_rejected_via_http():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            # No access_token and no request_id provided
            "query_params": {"region": "Sundarbans-North"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    error_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
    assert "valid access grant required" in error_msg.lower()


def test_d2_tokenless_retrieval_cannot_implicitly_create_grant(tmp_path):
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.artifact_store import ArtifactStore
    from models import CapabilityRetrieveRequest
    import pytest

    grant_store = ArtifactStore(reports_dir=str(tmp_path / "d2_grants"))
    service = CapabilityRegistryService(
        store_dir=str(tmp_path / "d2_cap_store"),
        grant_store=grant_store,
    )

    initial_grants_count = len(service._access_contracts)
    ret_req = CapabilityRetrieveRequest(
        application_id="consumer-app",
        # access_token and request_id both omitted
    )

    with pytest.raises(CapabilityAccessDeniedError) as exc_info:
        service.retrieve(
            actor="consumer-app",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )

    assert "valid access grant required" in str(exc_info.value).lower()
    # Explicitly verify NO grant was created in memory or storage
    assert len(service._access_contracts) == initial_grants_count


def test_d2_omitted_token_cannot_bypass_revocation():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Request access
    req_res = client.post(
        "/access/request",
        json={
            "application_id": "DATA_CONSUMER",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers=headers,
    )
    assert req_res.status_code == 200
    grant = req_res.json()

    # 2. Revoke grant
    del_res = client.delete(f"/access/{grant['request_id']}", headers=headers)
    assert del_res.status_code == 200

    # 3. Retrieval with revoked token fails closed
    ret_revoked = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": grant["access_token"],
        },
        headers=headers,
    )
    assert ret_revoked.status_code == 403
    assert "revoked" in ret_revoked.text.lower()

    # 4. Retrieval attempting to omit token to bypass revocation also fails closed
    ret_omitted = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
        },
        headers=headers,
    )
    assert ret_omitted.status_code == 403
    assert "valid access grant required" in ret_omitted.text.lower()


def test_d2_retrieval_with_invalid_or_unrecognized_token_rejected():
    token = _get_token(actor="DATA_CONSUMER", roles=["ecosystem-reader"])
    res = client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        json={
            "application_id": "DATA_CONSUMER",
            "access_token": "grant-nonexistent-token-12345",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    error_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
    assert "valid access grant required" in error_msg.lower()


def test_d2_retrieval_denial_audit_emission(tmp_path):
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.crypto_audit_emitter import CryptoAuditEmitter
    from models import CapabilityRetrieveRequest
    import pytest

    audit_emitter = CryptoAuditEmitter()
    service = CapabilityRegistryService(
        store_dir=str(tmp_path / "d2_cap_store"),
        audit_emitter=audit_emitter,
    )

    ret_req = CapabilityRetrieveRequest(
        application_id="DATA_CONSUMER",
        trace_id="test-trace-d2-001",
        execution_id="test-exec-d2-001",
    )

    with pytest.raises(CapabilityAccessDeniedError):
        service.retrieve(
            actor="DATA_CONSUMER",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )

    chain = audit_emitter.get_chain()
    denial_entries = [
        e for e in chain
        if e.payload.get("action") == "DATA_RETRIEVAL"
        and e.payload.get("result") == "DENIED"
    ]
    assert len(denial_entries) >= 1
    assert "valid access grant required" in denial_entries[-1].payload.get("reason", "").lower()


def test_d2_revoked_persisted_grant_rejected_despite_local_cache(tmp_path):
    """
    Remediation B: In a multi-worker deployment, Worker 1 must reject a grant that
    was revoked by Worker 2 even if Worker 1 already has the contract in its local heap cache.
    """
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.artifact_store import ArtifactStore
    from models import CapabilityAccessRequest, CapabilityRetrieveRequest
    import pytest

    shared_grant_store = ArtifactStore(reports_dir=str(tmp_path / "shared_grants"))
    store_dir = str(tmp_path / "shared_cap_store")

    # Worker 1 creates grant
    worker_1 = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={"worker-actor": ["worker-app"]},
    )
    acc_req = CapabilityAccessRequest(
        application_id="worker-app",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    grant = worker_1.request_access(actor="worker-actor", roles=["ecosystem-reader"], request_data=acc_req)
    token = grant.access_token

    # Worker 1 populates its in-memory cache
    assert worker_1.get_access_contract(token) is not None
    assert token in worker_1._access_contracts

    # Worker 2 revokes the grant in shared storage
    worker_2 = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={"worker-actor": ["worker-app"]},
    )
    worker_2.revoke_access_contract(token, actor="worker-actor", reason="Revoked via Worker 2")

    # Worker 1 now retrieves: authoritative store resolution MUST reject it despite Worker 1's local cache
    assert worker_1.get_access_contract(token) is None
    # Stale local cache entry must be evicted
    assert token not in worker_1._access_contracts

    ret_req = CapabilityRetrieveRequest(
        application_id="worker-app",
        access_token=token,
    )
    with pytest.raises(CapabilityAccessDeniedError) as exc_info:
        worker_1.retrieve(
            actor="worker-actor",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )
    assert "revoked" in str(exc_info.value).lower()


def test_d2_missing_persisted_record_invalidates_cache_and_denies(tmp_path):
    """
    Remediation B: If a grant record is missing or deleted from authoritative storage,
    cached entries are evicted and retrieval fails closed.
    """
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.artifact_store import ArtifactStore
    from models import CapabilityAccessRequest, CapabilityRetrieveRequest
    import pytest

    shared_grant_store = ArtifactStore(reports_dir=str(tmp_path / "missing_record_grants"))
    store_dir = str(tmp_path / "missing_record_cap_store")

    service = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={"worker-actor": ["worker-app"]},
    )
    acc_req = CapabilityAccessRequest(
        application_id="worker-app",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    grant = service.request_access(actor="worker-actor", roles=["ecosystem-reader"], request_data=acc_req)
    token = grant.access_token

    # Verify cache is populated
    assert token in service._access_contracts

    # Delete record from persistent store
    shared_grant_store.delete(token)

    # Retrieval must fail closed and evict local cache
    assert service.get_access_contract(token) is None
    assert token not in service._access_contracts

    ret_req = CapabilityRetrieveRequest(
        application_id="worker-app",
        access_token=token,
    )
    with pytest.raises(CapabilityAccessDeniedError) as exc_info:
        service.retrieve(
            actor="worker-actor",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )
    assert "valid access grant required" in str(exc_info.value).lower()


def test_d2_store_read_failure_fails_closed_despite_cache(tmp_path, monkeypatch):
    """
    Remediation B: When authoritative store read raises an error (I/O, corruption),
    access fails closed immediately and does not fall back to local memory cache.
    """
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.artifact_store import ArtifactStore
    from models import CapabilityAccessRequest, CapabilityRetrieveRequest
    import pytest

    shared_grant_store = ArtifactStore(reports_dir=str(tmp_path / "io_error_grants"))
    store_dir = str(tmp_path / "io_error_cap_store")

    service = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={"worker-actor": ["worker-app"]},
    )
    acc_req = CapabilityAccessRequest(
        application_id="worker-app",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    grant = service.request_access(actor="worker-actor", roles=["ecosystem-reader"], request_data=acc_req)
    token = grant.access_token

    # Cache is populated
    assert token in service._access_contracts

    # Simulate I/O failure on persistent store read
    def failing_load(*args, **kwargs):
        raise IOError("Disk read error or network storage disconnect")

    monkeypatch.setattr(shared_grant_store, "load", failing_load)

    # Must fail closed: returns None, evicts cache
    assert service.get_access_contract(token) is None
    assert token not in service._access_contracts

    ret_req = CapabilityRetrieveRequest(
        application_id="worker-app",
        access_token=token,
    )
    with pytest.raises(CapabilityAccessDeniedError):
        service.retrieve(
            actor="worker-actor",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )


def test_d2_malformed_persisted_record_fails_closed(tmp_path):
    """
    Remediation B: If persisted grant record is malformed or invalid JSON/dict,
    access fails closed and evicts any local cache.
    """
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.artifact_store import ArtifactStore
    from models import CapabilityRetrieveRequest
    import pytest

    shared_grant_store = ArtifactStore(reports_dir=str(tmp_path / "malformed_grants"))
    store_dir = str(tmp_path / "malformed_cap_store")

    # Manually save malformed record
    shared_grant_store.save("grant-corrupted-token", {"contract": "invalid-non-dict-string", "revoked": False})

    service = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={"worker-actor": ["worker-app"]},
    )
    assert service.get_access_contract("grant-corrupted-token") is None

    ret_req = CapabilityRetrieveRequest(
        application_id="worker-app",
        access_token="grant-corrupted-token",
    )
    with pytest.raises(CapabilityAccessDeniedError):
        service.retrieve(
            actor="worker-actor",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )


def test_d2_mismatched_persisted_record_fails_closed(tmp_path):
    """
    Task B: If persistent grant record contains a contract whose access_token
    and request_id do not match the requested key, fail closed and evict cache.
    """
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.artifact_store import ArtifactStore
    from models import CapabilityRetrieveRequest, AccessContract
    import pytest
    from datetime import datetime, timezone, timedelta

    shared_grant_store = ArtifactStore(reports_dir=str(tmp_path / "mismatch_grants"))
    store_dir = str(tmp_path / "mismatch_cap_store")

    contract = AccessContract(
        request_id="req-legit-123",
        application_id="worker-app",
        capability_id="cap-mangrove-monitoring",
        capability_version="1.0.0",
        contract_version="1.0.0",
        purpose="environmental_monitoring",
        authorized=True,
        access_token="tok-legit-abc",
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    # Save contract under an arbitrary/mismatched key "hijacked-key"
    record = {
        "contract": contract.model_dump(mode="json"),
        "actor": "worker-actor",
        "revoked": False,
    }
    shared_grant_store.save("hijacked-key", record)

    service = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={"worker-actor": ["worker-app"]},
    )

    # get_access_contract for mismatched key must return None
    assert service.get_access_contract("hijacked-key") is None

    ret_req = CapabilityRetrieveRequest(
        application_id="worker-app",
        access_token="hijacked-key",
    )
    with pytest.raises(CapabilityAccessDeniedError):
        service.retrieve(
            actor="worker-actor",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )


def test_d2_authoritative_actor_metadata_populated_across_workers(tmp_path):
    """
    Task B: Grant actor metadata is populated from the authoritative persistent record
    when a separate worker loads the grant.
    """
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.artifact_store import ArtifactStore
    from models import CapabilityAccessRequest, CapabilityRetrieveRequest
    import pytest

    shared_grant_store = ArtifactStore(reports_dir=str(tmp_path / "cross_worker_grants"))
    store_dir = str(tmp_path / "cross_worker_cap_store")

    # Worker 1 issues the grant
    service1 = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={"authorized-actor": ["app-geo"]},
    )
    acc_req = CapabilityAccessRequest(
        application_id="app-geo",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    grant = service1.request_access(
        actor="authorized-actor",
        roles=["ecosystem-reader"],
        request_data=acc_req,
    )

    # Worker 2 has empty in-memory cache but shares grant_store
    service2 = CapabilityRegistryService(
        store_dir=store_dir,
        grant_store=shared_grant_store,
        actor_application_entitlements={
            "authorized-actor": ["app-geo"],
            "impostor-actor": ["app-geo"],
        },
    )

    # Verify actor is populated from persistent record
    resolved_actor = service2.get_access_contract_actor(grant.access_token)
    assert resolved_actor == "authorized-actor"

    # Authorized actor can retrieve
    ret_req = CapabilityRetrieveRequest(
        application_id="app-geo",
        access_token=grant.access_token,
    )
    result = service2.retrieve(
        actor="authorized-actor",
        roles=["ecosystem-reader"],
        capability_id="cap-mangrove-monitoring",
        retrieve_req=ret_req,
    )
    assert result.data is not None
    assert result.request_id == grant.request_id

    # Impostor actor with different identity is rejected
    with pytest.raises(CapabilityAccessDeniedError) as exc_info:
        service2.retrieve(
            actor="impostor-actor",
            roles=["ecosystem-reader"],
            capability_id="cap-mangrove-monitoring",
            retrieve_req=ret_req,
        )
    assert "bound to actor 'authorized-actor', cannot be used by 'impostor-actor'" in str(exc_info.value)
