from tests.test_identity_fixtures import get_test_token
"""
Tests for MASTERDB Capability Access Authorization & Policy Evaluation.
"""
import uuid

from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def _get_token(actor="auth-tester", roles=None):
    return get_test_token(actor=actor, roles=roles)


def test_request_access_success():
    token = _get_token(actor="VALID_CONSUMER", roles=["ecosystem-reader"])
    payload = {
        "application_id": "VALID_CONSUMER",
        "capability_id": "cap-mangrove-monitoring",
        "purpose": "environmental_monitoring",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    grant = res.json()
    assert grant["authorized"] is True
    assert grant["application_id"] == "VALID_CONSUMER"
    assert grant["capability_id"] == "cap-mangrove-monitoring"
    assert "access_token" in grant
    assert grant["access_token"].startswith("grant-")


def test_request_access_unauthorized_consumer():
    token = _get_token(actor="auth-tester")
    from models import Capability

    capability_id = f"cap-restricted-{uuid.uuid4().hex[:10]}"
    main.capability_registry_service.register_capability(
        Capability(
            capability_id=capability_id,
            capability_name="Classified Defense Dataset",
            description="Restricted classified intelligence capability",
            dataset_id="ds-defense-001",
            authorization_requirements={
                "required_roles": ["super-secret-admin"],
                "allowed_consumers": ["SPECIAL_DEFENSE_APP"],
            },
        )
    )

    payload = {
        "application_id": "UNAUTHORIZED_CONSUMER_APP",
        "capability_id": capability_id,
        "purpose": "unauthorized_access",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    body = res.json()
    assert "error" in body


def test_request_access_nonexistent_capability():
    token = _get_token()
    payload = {
        "application_id": "APP1",
        "capability_id": "invalid-cap-999",
        "purpose": "general_reuse",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404


def test_request_access_rejects_unapproved_purpose():
    token = _get_token(actor="VALID_CONSUMER", roles=["ecosystem-reader"])
    payload = {
        "application_id": "VALID_CONSUMER",
        "capability_id": "cap-mangrove-monitoring",
        "purpose": "unrelated_financial_analysis",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_request_access_rejects_unregistered_capability_version():
    token = _get_token(actor="VALID_CONSUMER", roles=["ecosystem-reader"])
    payload = {
        "application_id": "VALID_CONSUMER",
        "capability_id": "cap-mangrove-monitoring",
        "capability_version": "9.9.9",
        "purpose": "environmental_monitoring",
    }
    res = client.post("/access/request", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


def test_durable_grant_persistence_across_instances(tmp_path):
    from services.capability_registry_service import CapabilityRegistryService
    from services.artifact_store import ArtifactStore
    from models import CapabilityAccessRequest

    store_dir = str(tmp_path / "persist_test_cap_store")
    grant_store = ArtifactStore(reports_dir=str(tmp_path / "persist_test_grants"))

    svc1 = CapabilityRegistryService(store_dir=store_dir, grant_store=grant_store)
    access_req = CapabilityAccessRequest(
        application_id="PERSIST_APP",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    grant1 = svc1.request_access(actor="persist-tester", roles=["ecosystem-reader"], request_data=access_req)
    assert grant1.authorized is True

    # Fresh instance without memory cache
    svc2 = CapabilityRegistryService(store_dir=store_dir, grant_store=grant_store)
    loaded_grant = svc2.get_access_contract(grant1.access_token)
    assert loaded_grant is not None
    assert loaded_grant.request_id == grant1.request_id
    assert loaded_grant.application_id == "PERSIST_APP"
    assert loaded_grant.capability_id == "cap-mangrove-monitoring"


def test_rs256_token_access_request_authorization(monkeypatch):
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from main import auth_service

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    old_pubkey = auth_service.public_key_pem
    auth_service.public_key_pem = pub_pem
    try:
        # Valid RS256 token from tantra-sarathi for masterdb audience
        valid_token = jwt.encode(
            {
                "sub": "tantra-execution-agent",
                "roles": ["ecosystem-reader"],
                "iss": "tantra-sarathi",
                "aud": "masterdb",
            },
            priv_pem,
            algorithm="RS256",
        )
        res = client.post(
            "/access/request",
            json={
                "application_id": "VALID_CONSUMER",
                "capability_id": "cap-mangrove-monitoring",
                "purpose": "environmental_monitoring",
            },
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert res.status_code == 200
        assert res.json()["authorized"] is True

        # Invalid issuer
        bad_iss_token = jwt.encode(
            {
                "sub": "tantra-execution-agent",
                "roles": ["ecosystem-reader"],
                "iss": "evil-untrusted-issuer",
                "aud": "masterdb",
            },
            priv_pem,
            algorithm="RS256",
        )
        res_bad_iss = client.post(
            "/access/request",
            json={
                "application_id": "VALID_CONSUMER",
                "capability_id": "cap-mangrove-monitoring",
                "purpose": "environmental_monitoring",
            },
            headers={"Authorization": f"Bearer {bad_iss_token}"},
        )
        assert res_bad_iss.status_code == 401

        # Invalid audience
        bad_aud_token = jwt.encode(
            {
                "sub": "tantra-execution-agent",
                "roles": ["ecosystem-reader"],
                "iss": "tantra-sarathi",
                "aud": "other-service",
            },
            priv_pem,
            algorithm="RS256",
        )
        res_bad_aud = client.post(
            "/access/request",
            json={
                "application_id": "VALID_CONSUMER",
                "capability_id": "cap-mangrove-monitoring",
                "purpose": "environmental_monitoring",
            },
            headers={"Authorization": f"Bearer {bad_aud_token}"},
        )
        assert res_bad_aud.status_code == 401

        # Missing roles claim fails closed
        no_roles_token = jwt.encode(
            {
                "sub": "tantra-execution-agent",
                "iss": "tantra-sarathi",
                "aud": "masterdb",
            },
            priv_pem,
            algorithm="RS256",
        )
        res_no_roles = client.post(
            "/access/request",
            json={
                "application_id": "VALID_CONSUMER",
                "capability_id": "cap-mangrove-monitoring",
                "purpose": "environmental_monitoring",
            },
            headers={"Authorization": f"Bearer {no_roles_token}"},
        )
        assert res_no_roles.status_code == 401
    finally:
        auth_service.public_key_pem = old_pubkey


# =============================================================================
# D4: Server-Side Actor-to-Application Entitlement Regression Suite
# =============================================================================

def test_d4_actor_equals_application_id_without_explicit_entitlement_denied():
    # Remediation A: Self-representation alone is NOT sufficient proof of entitlement.
    # An actor whose name matches application_id but lacks explicit entitlement MUST be denied.
    token = _get_token(actor="unentitled-direct-consumer", roles=["ecosystem-reader"])
    res = client.post(
        "/access/request",
        json={
            "application_id": "unentitled-direct-consumer",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    error_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
    assert "not entitled to represent application" in error_msg.lower()


def test_d4_actor_with_explicit_env_entitlement_allowed(monkeypatch):
    # Legitimate entitlement explicitly configured via environment is authorized
    monkeypatch.setenv("AUTH_ENTITLED_APPS_EXPLICIT_CONSUMER", "explicit-consumer")
    token = _get_token(actor="explicit-consumer", roles=["ecosystem-reader"])
    res = client.post(
        "/access/request",
        json={
            "application_id": "explicit-consumer",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["authorized"] is True
    assert body["application_id"] == "explicit-consumer"


def test_d4_actor_with_explicit_injected_entitlement_case_insensitive(tmp_path):
    from services.capability_registry_service import CapabilityRegistryService
    from models import CapabilityAccessRequest

    service = CapabilityRegistryService(
        store_dir=str(tmp_path / "d4_injected_case_store"),
        actor_application_entitlements={"agent-worker": ["MANAGED-CONSUMER-APP"]},
    )
    acc_req = CapabilityAccessRequest(
        application_id="managed-consumer-app",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    contract = service.request_access(
        actor="AGENT-WORKER",
        roles=["ecosystem-reader"],
        request_data=acc_req,
    )
    assert contract.authorized is True
    assert contract.application_id == "managed-consumer-app" 


def test_d4_actor_delegation_via_env_allowed(monkeypatch):
    monkeypatch.setenv("AUTH_ENTITLED_APPS_SPECIAL_AGENT", "CUSTOM_DELEGATED_APP,ANOTHER_APP")
    token = _get_token(actor="special-agent", roles=["ecosystem-reader"])
    res = client.post(
        "/access/request",
        json={
            "application_id": "CUSTOM_DELEGATED_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["authorized"] is True


def test_d4_actor_delegation_via_injected_mapping_allowed(tmp_path):
    from services.capability_registry_service import CapabilityRegistryService
    from models import CapabilityAccessRequest

    service = CapabilityRegistryService(
        store_dir=str(tmp_path / "d4_injected_store"),
        actor_application_entitlements={"worker-bot": ["managed-service-app", "cluster-app"]},
    )
    acc_req = CapabilityAccessRequest(
        application_id="managed-service-app",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    contract = service.request_access(
        actor="worker-bot",
        roles=["ecosystem-reader"],
        request_data=acc_req,
    )
    assert contract.authorized is True
    assert contract.application_id == "managed-service-app"


def test_d4_unauthorized_impersonation_denied():
    token = _get_token(actor="rogue-caller", roles=["ecosystem-reader"])
    res = client.post(
        "/access/request",
        json={
            "application_id": "UNAUTHORIZED_TARGET_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    error_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
    assert "not entitled to represent application" in error_msg.lower()


def test_d4_admin_role_cannot_bypass_application_entitlement():
    # Admin roles (admin / bhiv-admin) cannot claim arbitrary application identity without entitlement
    token = _get_token(actor="super-admin-user", roles=["admin", "bhiv-admin"])
    res = client.post(
        "/access/request",
        json={
            "application_id": "ARBITRARY_UNENTITLED_APP",
            "capability_id": "cap-mangrove-monitoring",
            "purpose": "environmental_monitoring",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    error_msg = res.json().get("detail") or res.json().get("error", {}).get("message", "")
    assert "not entitled to represent application" in error_msg.lower()


def test_d4_missing_or_empty_actor_fails_closed(tmp_path):
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from models import CapabilityAccessRequest
    import pytest

    service = CapabilityRegistryService(store_dir=str(tmp_path / "d4_empty_actor_store"))
    acc_req = CapabilityAccessRequest(
        application_id="some-app",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    with pytest.raises(CapabilityAccessDeniedError) as exc_info:
        service.request_access(actor="", roles=["ecosystem-reader"], request_data=acc_req)
    assert "actor identity is required" in str(exc_info.value).lower()


def test_d4_audit_emission_on_entitlement_denial(tmp_path):
    from services.capability_registry_service import CapabilityRegistryService, CapabilityAccessDeniedError
    from services.crypto_audit_emitter import CryptoAuditEmitter
    from models import CapabilityAccessRequest
    import pytest

    audit_emitter = CryptoAuditEmitter()
    service = CapabilityRegistryService(
        store_dir=str(tmp_path / "d4_audit_cap_store"),
        audit_emitter=audit_emitter,
    )
    acc_req = CapabilityAccessRequest(
        application_id="impersonated-app",
        capability_id="cap-mangrove-monitoring",
        purpose="environmental_monitoring",
    )
    with pytest.raises(CapabilityAccessDeniedError):
        service.request_access(
            actor="unentitled-actor",
            roles=["ecosystem-reader"],
            request_data=acc_req,
        )

    chain = audit_emitter.get_chain()
    denial_entries = [
        e for e in chain
        if e.payload.get("action") == "ACCESS_REQUEST"
        and e.payload.get("result") == "DENIED"
        and e.actor == "unentitled-actor"
    ]
    assert len(denial_entries) >= 1
    assert "not entitled" in denial_entries[-1].payload.get("reason", "").lower()
