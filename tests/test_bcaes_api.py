import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Each test gets an empty BCAES registry, independent of any other
    test module's shared app state."""
    main.bcaes_registry_service = main.BCAESRegistryService()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _auth_headers(actor="Kavy", roles=None):
    token, _ = main.auth_service.issue_token(actor, roles or [])
    return {"Authorization": f"Bearer {token}"}


def _register(client, registry_type, name, owner="Kavy", dependencies=None):
    body = {
        "name": name,
        "purpose": f"{name} purpose",
        "owner": owner,
        "authority_boundaries": [owner],
        "dependencies": dependencies or [],
    }
    resp = client.post(
        f"/bcaes/registries/{registry_type}/objects", json=body, headers=_auth_headers(actor=owner)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_register_and_get_object(client):
    created = _register(client, "capability", "Schema Validation")
    resp = client.get(f"/bcaes/registries/capability/objects/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Schema Validation"


def test_register_without_token_returns_401(client):
    resp = client.post(
        "/bcaes/registries/capability/objects",
        json={"name": "X", "purpose": "p", "owner": "Kavy", "authority_boundaries": ["Kavy"]},
    )
    assert resp.status_code == 401


def test_register_with_actor_not_in_authority_boundaries_returns_403(client):
    resp = client.post(
        "/bcaes/registries/capability/objects",
        json={"name": "X", "purpose": "p", "owner": "Kavy", "authority_boundaries": ["Kavy"]},
        headers=_auth_headers(actor="SomeoneElse"),
    )
    assert resp.status_code == 403


def test_register_with_admin_role_bypasses_authority_check(client):
    resp = client.post(
        "/bcaes/registries/capability/objects",
        json={"name": "X", "purpose": "p", "owner": "Kavy", "authority_boundaries": ["Kavy"]},
        headers=_auth_headers(actor="SomeoneElse", roles=["bhiv-admin"]),
    )
    assert resp.status_code == 200


def test_unknown_registry_type_returns_404(client):
    resp = client.get("/bcaes/registries/not_a_registry/objects")
    assert resp.status_code == 404


def test_get_missing_object_returns_404(client):
    resp = client.get("/bcaes/registries/capability/objects/cap-missing")
    assert resp.status_code == 404


def test_register_with_missing_dependency_returns_400(client):
    resp = client.post(
        "/bcaes/registries/platform_service/objects",
        json={
            "name": "Svc",
            "purpose": "p",
            "owner": "Kavy",
            "authority_boundaries": ["Kavy"],
            "dependencies": [{"id": "cap-ghost"}],
        },
        headers=_auth_headers(actor="Kavy"),
    )
    assert resp.status_code == 400


def test_list_registries_summary(client):
    _register(client, "domain", "Knowledge Domain")
    resp = client.get("/bcaes/registries")
    assert resp.status_code == 200
    body = resp.json()
    assert body["registries"]["domain"] == 1
    assert body["registries"]["capability"] == 0


def test_search_by_query(client):
    _register(client, "capability", "Duplicate Detection")
    _register(client, "capability", "Version Negotiation")
    resp = client.get("/bcaes/search", params={"q": "duplicate"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["name"] == "Duplicate Detection"


def test_relationships_and_dependency_explorer(client):
    domain = _register(client, "domain", "Ingestion Domain")
    capability = _register(
        client, "capability", "Certification Capability",
        dependencies=[{"id": domain["id"]}],
    )
    rel = client.get(f"/bcaes/relationships/{capability['id']}")
    assert rel.status_code == 200
    assert rel.json()["dependencies"] == [{"id": domain["id"], "required_version": None}]

    deps = client.get(f"/bcaes/dependencies/{capability['id']}")
    assert deps.status_code == 200
    assert domain["id"] in deps.json()["transitive_dependencies"]

    domain_after = client.get(f"/bcaes/registries/domain/objects/{domain['id']}")
    assert domain_after.json()["consumers"] == [capability["id"]]


def test_capability_reuse_check_endpoint(client):
    _register(client, "capability", "Duplicate Detection")
    resp = client.get("/bcaes/capability-reuse-check", params={"name": "Duplicate Detection"})
    assert resp.status_code == 200
    assert resp.json()["reuse_recommended"] is True


def test_validate_architecture_endpoint_is_replay_safe(client):
    _register(client, "capability", "Schema Validation")
    first = client.get("/bcaes/validate/architecture").json()
    second = client.get("/bcaes/validate/architecture").json()
    assert first["replay_hash"] == second["replay_hash"]
    assert first["passed"] is True


def test_validate_duplicates_endpoint_flags_conflict(client):
    _register(client, "capability", "Same Name")
    _register(client, "capability", "same name")
    resp = client.get("/bcaes/validate/duplicates")
    body = resp.json()
    assert body["passed"] is False


def test_update_object(client):
    created = _register(client, "engine", "Scoring Engine")
    resp = client.patch(
        f"/bcaes/registries/engine/objects/{created['id']}",
        json={"status": "active", "version": "2.0"},
        headers=_auth_headers(actor="Kavy"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["version"] == "2.0"


def test_update_object_without_authority_returns_403(client):
    created = _register(client, "engine", "Scoring Engine")
    resp = client.patch(
        f"/bcaes/registries/engine/objects/{created['id']}",
        json={"status": "active"},
        headers=_auth_headers(actor="SomeoneElse"),
    )
    assert resp.status_code == 403


def test_delete_object(client):
    created = _register(client, "framework", "Retry Framework")
    resp = client.delete(
        f"/bcaes/registries/framework/objects/{created['id']}", headers=_auth_headers(actor="Kavy")
    )
    assert resp.status_code == 200
    followup = client.get(f"/bcaes/registries/framework/objects/{created['id']}")
    assert followup.status_code == 404


def test_delete_object_without_token_returns_401(client):
    created = _register(client, "framework", "Retry Framework")
    resp = client.delete(f"/bcaes/registries/framework/objects/{created['id']}")
    assert resp.status_code == 401
