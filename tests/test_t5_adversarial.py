"""
T5 Adversarial Security Test Suite for MASTERDB.
Executes 10 attack vectors against the hardened access control layer.
Discovers and documents remaining defects and verifies fail-closed boundaries.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import jwt
import pytest
from fastapi.testclient import TestClient

import main
from auth.constants import ADMIN_ROLE
from auth.models import AuthIdentity
from models import PackageStatus, CapabilityRetrieveRequest
from auth.service import AuthService, AuthTokenError
from bcaes_registry.models import RegisterObjectRequest, RegistryType
from bcaes_registry.service import BCAESRegistryService, _has_authority
from operational_sync.service import _check

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    main.app.dependency_overrides.clear()
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def _make_token(actor: str = "attacker", roles: list = None, exp_delta: timedelta = timedelta(hours=1)) -> str:
    if roles is None:
        roles = ["viewer"]
    payload = {
        "sub": actor,
        "roles": roles,
        "exp": datetime.now(timezone.utc) + exp_delta,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, main.auth_service._secret_key, algorithm="HS256")


# ---------------------------------------------------------------------------
# ATTACK 1: PRIVILEGE ESCALATION
# Viewer role token attempts admin-only operations:
# - POST /admin/backup
# - POST /admin/restore
# - DELETE on protected resources
# ---------------------------------------------------------------------------
def test_1_privilege_escalation_viewer_blocked_on_admin_operations(client):
    viewer_token = _make_token("viewer-attacker", ["viewer"])
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # 1. Attempt backup with viewer role
    resp_backup = client.post("/admin/backup", headers=headers)
    assert resp_backup.status_code == 403, f"Expected 403 on backup, got {resp_backup.status_code}"
    assert "DENY:INSUFFICIENT_ROLE" in resp_backup.text

    # Also test GET /admin/backup
    resp_backup_get = client.get("/admin/backup", headers=headers)
    assert resp_backup_get.status_code == 403
    assert "DENY:INSUFFICIENT_ROLE" in resp_backup_get.text

    # 2. Attempt restore with viewer role
    resp_restore = client.post("/admin/restore", json={"stores": {}}, headers=headers)
    assert resp_restore.status_code == 403, f"Expected 403 on restore, got {resp_restore.status_code}"
    assert "DENY:INSUFFICIENT_ROLE" in resp_restore.text

    # 3. Attempt DELETE on protected BCAES resource
    resp_delete = client.delete("/bcaes/registries/capability/objects/cap-target", headers=headers)
    assert resp_delete.status_code in (403, 404), f"Expected 403 or 404, got {resp_delete.status_code}"
    if resp_delete.status_code == 403:
        assert "DENY:INSUFFICIENT_ROLE" in resp_delete.text


# ---------------------------------------------------------------------------
# ATTACK 2: FORGED ROLE CLAIMS
# Token issued with viewer role, request body contains roles=["bhiv-admin"] or actor="admin"
# Verify server ignores body roles/actor and uses only token claims
# ---------------------------------------------------------------------------
def test_2_forged_role_claims_ignored(client):
    viewer_token = _make_token("viewer-attacker", ["viewer"])
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # Body contains forged privileged roles and admin actor claim
    forged_body = {
        "package_id": "pkg-forged-001",
        "to_status": "INGESTED",
        "actor": "admin",
        "roles": ["bhiv-admin", "admin"],
        "reason": "Attempting forged privilege promotion",
    }
    resp = client.post("/packages/promote", json=forged_body, headers=headers)
    # Server must deny based on the token's viewer role, ignoring forged body claims
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "DENY:INSUFFICIENT_ROLE" in resp.text


# ---------------------------------------------------------------------------
# ATTACK 3: DEFAULT-ALLOW FAILURES
# Call bcaes_registry._has_authority(actor=None) directly
# Call operational_sync._check(actor=None) directly
# Verify both return DENY, not ALLOW
# ---------------------------------------------------------------------------
def test_3_default_allow_failures_prevented():
    # Direct call to bcaes_registry authority check with actor=None must be False (DENY)
    bcaes_result = _has_authority(actor=None, actor_roles=["admin", "bhiv-admin"], boundaries=["Kavy"])
    assert bcaes_result is False, "bcaes_registry._has_authority(None) must fail-closed (False)"

    # Direct call to operational_sync check with actor=None must raise PermissionError (DENY)
    with pytest.raises(PermissionError) as exc_info:
        _check(actor=None, actor_roles=["admin"], required_role="parikshak-sync")
    assert "DENY:MISSING_IDENTITY" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ATTACK 4: AUTHORIZATION BYPASS VIA ALTERNATIVE ROUTES
# Try accessing protected data through unauthenticated read endpoints
# Document which read endpoints still have no auth
# ---------------------------------------------------------------------------
def test_4_authorization_bypass_alternative_read_routes(client):
    unprotected_read_routes = []

    # 1. GET /datasets
    r1 = client.get("/datasets")
    if r1.status_code == 200:
        unprotected_read_routes.append("/datasets")

    # 2. GET /packages/{package_id}
    r2 = client.get("/packages/pkg-test-probe")
    if r2.status_code in (200, 404):  # Reached handler without 401/403
        unprotected_read_routes.append("/packages/{package_id}")

    # 3. GET /shared/registry
    r3 = client.get("/shared/registry")
    if r3.status_code == 200:
        unprotected_read_routes.append("/shared/registry")

    # 4. GET /pravah/ledger
    r4 = client.get("/pravah/ledger")
    if r4.status_code == 200:
        unprotected_read_routes.append("/pravah/ledger")

    # Verify that unauthenticated reads are detected and documented
    # Note: These are documented defects (T2 focused strictly on write/mutation paths)
    assert len(unprotected_read_routes) > 0, "Expected to find unauthenticated read routes"


# ---------------------------------------------------------------------------
# ATTACK 5: INCONSISTENT DECISIONS
# Same request sent twice with same token — verify outcome is identical both times
# ---------------------------------------------------------------------------
def test_5_inconsistent_decisions_deterministic(client):
    token = _make_token("test-operator-deterministic", ["operator"])
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "dataset_path": str(ROOT / "datasets" / "certifiable_sample.csv"),
        "metadata_path": str(ROOT / "datasets" / "metadata.json"),
        "dataset_id": "test-deterministic-ds",
    }

    # Request 1
    resp1 = client.post("/validate", json=payload, headers=headers)
    # Request 2 (identical request and credentials)
    resp2 = client.post("/validate", json=payload, headers=headers)

    assert resp1.status_code == resp2.status_code, "Decisions must be consistent"
    assert resp1.json()["state"] == resp2.json()["state"], "Results must be deterministic"


# ---------------------------------------------------------------------------
# ATTACK 6: EXPIRED TOKEN ATTACK
# Manually craft a JWT with exp in the past — verify DENY:INVALID_CREDENTIALS returned
# ---------------------------------------------------------------------------
def test_6_expired_token_attack(client):
    expired_token = _make_token("expired-attacker", ["operator"], exp_delta=-timedelta(hours=2))
    headers = {"Authorization": f"Bearer {expired_token}"}

    resp = client.post(
        "/packages/register",
        json={"dataset_id": "ds-expired-attack"},
        headers=headers,
    )
    assert resp.status_code == 401, f"Expected 401 for expired token, got {resp.status_code}"
    assert "DENY:INVALID_CREDENTIALS" in resp.text or "expired" in resp.text.lower()


# ---------------------------------------------------------------------------
# ATTACK 7: NONE/NULL INJECTION
# Send requests with Bearer null, Bearer None, Bearer undefined
# Verify all return DENY (401), not 500
# ---------------------------------------------------------------------------
def test_7_none_null_injection(client):
    injections = ["null", "None", "undefined", "nil", "0"]
    for val in injections:
        headers = {"Authorization": f"Bearer {val}"}
        resp = client.post("/packages/register", json={"dataset_id": "ds-null-test"}, headers=headers)
        assert resp.status_code in (401, 403), f"Expected 401/403 for Bearer {val}, got {resp.status_code}"
        assert resp.status_code != 500, f"Bearer {val} caused internal server error 500!"


# ---------------------------------------------------------------------------
# ATTACK 8: ADMIN PASSWORD UNSET ESCALATION
# With ADMIN_PASSWORD unset in env, attempt to get admin token via AUTH_PASSWORD
# Verify DENY:MISSING_ADMIN_PASSWORD (not admin grant)
# ---------------------------------------------------------------------------
def test_8_admin_password_unset_escalation_blocked(client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD", "standard-auth-password")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    resp = client.post(
        "/auth/token",
        json={"actor": "kavy", "password": "standard-auth-password"},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "DENY:MISSING_ADMIN_PASSWORD" in resp.text


# ---------------------------------------------------------------------------
# ATTACK 9: BCAES SELF-AUTHORIZATION (GAP 11 from audit)
# Viewer creates resource with authority_boundaries=["viewer"]
# Verify whether they gain ongoing write access — document as defect if confirmed
# ---------------------------------------------------------------------------
def test_9_bcaes_self_authorization_defect_verified():
    # An unprivileged caller with viewer role passes authority check if boundaries contains 'viewer'
    # because `set(roles) & set(boundaries)` evaluates to True.
    viewer_roles = ["viewer"]
    boundary_with_viewer_role = ["viewer"]

    has_authority = _has_authority(actor="arbitrary-viewer", actor_roles=viewer_roles, boundaries=boundary_with_viewer_role)

    # Defect confirmation: Any user can self-authorize by defining their own broad role as the boundary
    assert has_authority is True, "Defect confirmed: role matching in authority_boundaries allows viewer self-authorization"


# ---------------------------------------------------------------------------
# ATTACK 10: CAPABILITY CONTRACT BYPASS (GAP 12 from audit)
# Call capability retrieve with no access_token and no request_id
# Verify whether auto-grant still occurs — document as defect if confirmed
# ---------------------------------------------------------------------------
def test_10_capability_contract_bypass_defect_verified():
    from services.capability_registry_service import CapabilityRegistryService
    from services.package_registry_service import PackageRegistryService

    pkg_reg = PackageRegistryService()
    cap_service = CapabilityRegistryService(package_registry=pkg_reg)
    capability_id = "cap-mangrove-monitoring"
    assert cap_service.get_capability(capability_id) is not None

    # Call retrieve with NO access_token and NO request_id
    retrieve_req = CapabilityRetrieveRequest(
        application_id="anonymous-app",
        access_token=None,
        request_id=None,
    )

    # Calling retrieve directly without prior access token or request_id
    response = cap_service.retrieve(
        actor="anonymous-actor",
        roles=["ecosystem-reader"],
        capability_id=capability_id,
        retrieve_req=retrieve_req,
    )

    # Defect confirmation (GAP 12):
    # Instead of failing closed with 401/403 or rejecting the missing credential,
    # the retrieve method executes the `if not has_explicit_credential` branch
    # and automatically grants an AccessContract on the fly.
    assert response is not None
    assert response.request_id is not None
    assert response.request_id.startswith("req-ret-")
