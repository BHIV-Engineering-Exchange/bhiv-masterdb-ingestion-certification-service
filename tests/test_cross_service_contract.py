import os
import json
import time
import uuid
import pytest
import jwt
from fastapi.testclient import TestClient
import main
from auth.service import AuthService
from services.artifact_store import ArtifactStore
from services.sql_artifact_store import SqlArtifactStore

SARATHI_KEYS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..", "Tantra", "TANTRA-Gated-Bridge-Infrastructure", "services", "sarathi", "keys"
    )
)
SARATHI_PRIVATE_KEY_PATH = os.path.join(SARATHI_KEYS_DIR, "private.pem")
SARATHI_PUBLIC_KEY_PATH = os.path.join(SARATHI_KEYS_DIR, "public.pem")


@pytest.fixture(scope="module")
def sarathi_keys():
    assert os.path.exists(SARATHI_PRIVATE_KEY_PATH), f"Sarathi private key not found at {SARATHI_PRIVATE_KEY_PATH}"
    assert os.path.exists(SARATHI_PUBLIC_KEY_PATH), f"Sarathi public key not found at {SARATHI_PUBLIC_KEY_PATH}"
    with open(SARATHI_PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
        priv = f.read()
    with open(SARATHI_PUBLIC_KEY_PATH, "r", encoding="utf-8") as f:
        pub = f.read()
    return {"private": priv, "public": pub}


def issue_sarathi_jwt(
    sarathi_keys,
    actor="tantra-execution",
    roles=None,
    trace_id=None,
    execution_id=None,
    expired=False,
    bad_issuer=False,
    aud="masterdb",
    signing_key=None,
):
    if roles is None:
        roles = ["ecosystem-reader", "operator"]
    now = int(time.time())
    exp = (now - 60) if expired else (now + 3600)
    claims = {
        "iss": "invalid-issuer" if bad_issuer else "tantra-sarathi",
        "aud": aud,
        "sub": actor,
        "actor": actor,
        "roles": roles,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": exp,
    }
    if trace_id:
        claims["trace_id"] = trace_id
    if execution_id:
        claims["execution_id"] = execution_id

    key = signing_key or sarathi_keys["private"]
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def test_client(sarathi_keys, tmp_path):
    # Configure AuthService with Sarathi's public key (Option A asymmetric verification)
    main.auth_service.public_key_pem = sarathi_keys["public"]
    main.app.state.auth_service = main.auth_service

    # Configure durable grant store and SQL store for registry service
    grant_store = ArtifactStore(reports_dir=str(tmp_path / "cross_service_grants"))
    sql_store = SqlArtifactStore(f"sqlite:///{tmp_path}/cross_service.db", store_name="capabilities")

    main.capability_registry_service.grant_store = grant_store
    main.capability_registry_service.sql_store = sql_store

    return TestClient(main.app)


def test_cross_service_capability_discovery(test_client, sarathi_keys):
    token = issue_sarathi_jwt(sarathi_keys)
    response = test_client.get(
        "/capabilities?domain=geospatial",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    cap_ids = [c["capability_id"] for c in data]
    assert "cap-mangrove-monitoring" in cap_ids


def test_cross_service_capability_contract(test_client, sarathi_keys):
    token = issue_sarathi_jwt(sarathi_keys)
    response = test_client.get(
        "/capabilities/cap-mangrove-monitoring/contract",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    contract = response.json()
    assert contract["capability_id"] == "cap-mangrove-monitoring"
    assert "access_endpoint" in contract


def test_cross_service_access_grant_and_retrieval(test_client, sarathi_keys):
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"
    token = issue_sarathi_jwt(sarathi_keys, trace_id=trace_id, execution_id=execution_id)

    # 1. Request access grant
    access_payload = {
        "application_id": "app-tantra-gated-bridge",
        "capability_id": "cap-mangrove-monitoring",
        "purpose": "environmental_monitoring",
    }
    grant_res = test_client.post(
        "/access/request",
        headers={"Authorization": f"Bearer {token}"},
        json=access_payload
    )
    assert grant_res.status_code == 200
    grant = grant_res.json()
    assert grant["authorized"] is True
    assert grant["capability_id"] == "cap-mangrove-monitoring"
    grant_token = grant["access_token"]
    request_id = grant["request_id"]
    assert grant_token.startswith("grant-")

    # 2. Retrieve governed data
    retrieve_payload = {
        "application_id": "app-tantra-gated-bridge",
        "access_token": grant_token,
        "query_params": {"region": "Sundarbans-South"},
        "trace_id": trace_id,
        "execution_id": execution_id
    }
    ret_res = test_client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        headers={"Authorization": f"Bearer {token}"},
        json=retrieve_payload
    )
    assert ret_res.status_code == 200
    data = ret_res.json()
    assert data["capability"]["capability_id"] == "cap-mangrove-monitoring"
    assert data["trace_id"] == trace_id
    assert data["execution_id"] == execution_id
    assert "content_digest_sha256" in data
    assert len(data["content_digest_sha256"]) == 64
    assert "data" in data

    # 3. Revoke access grant
    revoke_res = test_client.delete(
        f"/access/{request_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"

    # 4. Subsequent retrieval with revoked grant must fail with 403 Forbidden
    denied_res = test_client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        headers={"Authorization": f"Bearer {token}"},
        json=retrieve_payload
    )
    assert denied_res.status_code == 403
    assert "revoked" in denied_res.text.lower()


def test_cross_service_rejects_expired_or_invalid_issuer_tokens(test_client, sarathi_keys):
    # Expired token
    expired_token = issue_sarathi_jwt(sarathi_keys, expired=True)
    res_exp = test_client.post(
        "/access/request",
        headers={"Authorization": f"Bearer {expired_token}"},
        json={"application_id": "app-test", "capability_id": "cap-mangrove-monitoring", "purpose": "test"}
    )
    assert res_exp.status_code == 401

    # Invalid issuer token
    bad_iss_token = issue_sarathi_jwt(sarathi_keys, bad_issuer=True)
    res_iss = test_client.post(
        "/access/request",
        headers={"Authorization": f"Bearer {bad_iss_token}"},
        json={"application_id": "app-test", "capability_id": "cap-mangrove-monitoring", "purpose": "test"}
    )
    assert res_iss.status_code == 401


def test_cross_service_rejects_invalid_signature_and_untrusted_audience(test_client, sarathi_keys):
    # 1. Invalid signature (corrupted token signature bytes)
    valid_token = issue_sarathi_jwt(sarathi_keys)
    header, payload, sig = valid_token.split(".")
    tampered_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    bad_sig_token = f"{header}.{payload}.{tampered_sig}"

    res_sig = test_client.get(
        "/capabilities",
        headers={"Authorization": f"Bearer {bad_sig_token}"}
    )
    assert res_sig.status_code == 401

    # 2. Untrusted audience
    bad_aud_token = issue_sarathi_jwt(sarathi_keys, aud="untrusted-target-audience")
    res_aud = test_client.get(
        "/capabilities",
        headers={"Authorization": f"Bearer {bad_aud_token}"}
    )
    assert res_aud.status_code == 401


def test_cross_service_rejects_expired_grant(test_client, sarathi_keys):
    from datetime import datetime, timedelta, timezone

    token = issue_sarathi_jwt(sarathi_keys)

    # 1. Request access grant
    grant_res = test_client.post(
        "/access/request",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "application_id": "app-tantra-gated-bridge",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        }
    )
    assert grant_res.status_code == 200
    grant = grant_res.json()
    grant_token = grant["access_token"]
    req_id = grant["request_id"]

    # 2. Manually mutate grant in memory and store to simulate past expiration
    past_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    contract = main.capability_registry_service._access_contracts.get(grant_token)
    assert contract is not None
    contract.expires_at = past_time

    # 3. Retrieve with expired contract -> must be rejected with 403 Forbidden
    retrieve_res = test_client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "application_id": "app-tantra-gated-bridge",
            "access_token": grant_token,
            "query_params": {}
        }
    )
    assert retrieve_res.status_code == 403
    assert "expired" in retrieve_res.text.lower()


def test_cross_service_rejects_nonexistent_capability_and_mismatched_app(test_client, sarathi_keys):
    token = issue_sarathi_jwt(sarathi_keys)

    # 1. Non-existent capability contract
    res_nonexistent = test_client.get(
        "/capabilities/cap-completely-nonexistent/contract",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_nonexistent.status_code == 404

    # 2. Grant requested for app-A cannot be retrieved by app-B
    grant_res = test_client.post(
        "/access/request",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "application_id": "app-tantra-original",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        }
    )
    assert grant_res.status_code == 200
    grant_token = grant_res.json()["access_token"]

    retrieve_mismatch = test_client.post(
        "/capabilities/cap-mangrove-monitoring/retrieve",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "application_id": "app-unauthorized-imposter",
            "access_token": grant_token,
            "query_params": {}
        }
    )
    assert retrieve_mismatch.status_code == 403
    assert "access contract is not valid" in retrieve_mismatch.text.lower()

