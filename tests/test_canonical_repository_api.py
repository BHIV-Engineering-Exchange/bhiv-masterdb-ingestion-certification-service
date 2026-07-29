import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def _fresh_repository():
    main.canonical_repository_service = main.CanonicalRepositoryService()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def _headers(actor="Kavy", roles=None):
    if roles is None:
        # covers the AccessPolicy defaults (read_roles=["ecosystem-reader"],
        # write_roles=["bcaes-editor"]) so tests aren't blocked by RBAC
        # unless they're specifically testing a denial.
        roles = ["ecosystem-reader", "bcaes-editor"]
    token, _ = main.auth_service.issue_token(actor, roles)
    return {"Authorization": f"Bearer {token}"}


def _register(client, category="bcaes_vol_4", headers=None, **overrides):
    body = {"category": category, "title": "BCAES Volume 4", "owner": "Kavy"}
    body.update(overrides)
    return client.post("/canonical-repository/documents", json=body, headers=headers or _headers())


def test_register_requires_token(client):
    resp = client.post(
        "/canonical-repository/documents",
        json={"category": "bcaes_vol_4", "title": "t", "owner": "Kavy"},
    )
    assert resp.status_code == 401


def test_register_without_write_role_returns_403(client):
    resp = _register(client, headers=_headers(roles=["ecosystem-reader"]))
    assert resp.status_code == 403


def test_register_creates_placeholder_by_default(client):
    resp = _register(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "placeholder"
    assert body["current_version"] == 1


def test_registered_placeholder_content_is_labeled(client):
    doc = _register(client).json()
    resp = client.get(f"/canonical-repository/documents/{doc['id']}/latest", headers=_headers())
    body = resp.json()
    assert body["is_placeholder"] is True
    assert "PLACEHOLDER" in body["content"]
    assert "bcaes_vol_4" in body["content"]


def test_read_without_read_role_returns_403(client):
    doc = _register(client).json()
    resp = client.get(
        f"/canonical-repository/documents/{doc['id']}/latest",
        headers=_headers(actor="Outsider", roles=["some-other-role"]),
    )
    assert resp.status_code == 403


def test_register_with_explicit_content_is_not_placeholder(client):
    resp = _register(client, category="bcaes_vol_5", initial_content="real seed text")
    body = resp.json()
    assert body["status"] == "draft"
    latest = client.get(f"/canonical-repository/documents/{body['id']}/latest", headers=_headers())
    assert latest.json()["is_placeholder"] is False
    assert latest.json()["content"] == "real seed text"


def test_duplicate_category_rejected(client):
    _register(client, category="bcaes_vol_6")
    resp = _register(client, category="bcaes_vol_6")
    assert resp.status_code == 409


def test_unknown_category_404(client):
    resp = client.get("/canonical-repository/by-category/not_a_volume", headers=_headers())
    assert resp.status_code == 404


def test_get_by_category(client):
    doc = _register(client, category="bcab").json()
    resp = client.get("/canonical-repository/by-category/bcab", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["id"] == doc["id"]


def test_publish_version_increments_and_updates_status(client):
    doc = _register(client).json()
    resp = client.post(
        f"/canonical-repository/documents/{doc['id']}/versions",
        json={"content": "Real BCAES Vol 4 text.", "change_note": "centrally populated", "published_by": "TaskLead"},
        headers=_headers(actor="TaskLead"),
    )
    assert resp.status_code == 200
    version = resp.json()
    assert version["version_number"] == 2
    assert version["is_placeholder"] is False

    updated_doc = client.get(f"/canonical-repository/documents/{doc['id']}", headers=_headers()).json()
    assert updated_doc["status"] == "published"
    assert updated_doc["current_version"] == 2


def test_publish_version_without_write_role_returns_403(client):
    doc = _register(client).json()
    resp = client.post(
        f"/canonical-repository/documents/{doc['id']}/versions",
        json={"content": "c", "change_note": "n", "published_by": "x"},
        headers=_headers(actor="Outsider", roles=["ecosystem-reader"]),
    )
    assert resp.status_code == 403


def test_publish_version_missing_document_404(client):
    resp = client.post(
        "/canonical-repository/documents/doc-nonexistent/versions",
        json={"content": "c", "change_note": "n", "published_by": "x"},
        headers=_headers(),
    )
    assert resp.status_code == 404


def test_version_history_is_append_only(client):
    doc = _register(client).json()
    client.post(
        f"/canonical-repository/documents/{doc['id']}/versions",
        json={"content": "v2", "change_note": "n", "published_by": "x"},
        headers=_headers(),
    )
    client.post(
        f"/canonical-repository/documents/{doc['id']}/versions",
        json={"content": "v3", "change_note": "n", "published_by": "x"},
        headers=_headers(),
    )
    resp = client.get(f"/canonical-repository/documents/{doc['id']}/versions", headers=_headers())
    versions = resp.json()["versions"]
    assert [v["version_number"] for v in versions] == [1, 2, 3]
    assert versions[0]["content"] != versions[1]["content"] != versions[2]["content"]


def test_get_specific_version(client):
    doc = _register(client).json()
    client.post(
        f"/canonical-repository/documents/{doc['id']}/versions",
        json={"content": "v2 text", "change_note": "n", "published_by": "x"},
        headers=_headers(),
    )
    resp = client.get(f"/canonical-repository/documents/{doc['id']}/versions/2", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["content"] == "v2 text"


def test_get_missing_version_404(client):
    doc = _register(client).json()
    resp = client.get(f"/canonical-repository/documents/{doc['id']}/versions/99", headers=_headers())
    assert resp.status_code == 404


def test_verify_chain_intact(client):
    doc = _register(client).json()
    client.post(
        f"/canonical-repository/documents/{doc['id']}/versions",
        json={"content": "v2", "change_note": "n", "published_by": "x"},
        headers=_headers(),
    )
    resp = client.get(f"/canonical-repository/documents/{doc['id']}/verify", headers=_headers())
    body = resp.json()
    assert body["chain_intact"] is True
    assert body["versions_checked"] == 2
    assert body["mismatched_versions"] == []


def test_list_documents(client):
    _register(client, category="bcaes_vol_1")
    _register(client, category="bcaes_vol_2")
    resp = client.get("/canonical-repository/documents", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_list_documents_filters_to_readable_ones(client):
    """An actor without the right read_roles doesn't get a 403 on list —
    they just don't see documents they can't read."""
    _register(client, category="bcaes_vol_1")
    resp = client.get(
        "/canonical-repository/documents", headers=_headers(actor="Outsider", roles=["nothing-relevant"])
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_admin_role_bypasses_both_read_and_write_checks(client):
    doc = _register(client, category="bcaes_vol_3").json()
    resp = client.get(
        f"/canonical-repository/documents/{doc['id']}", headers=_headers(actor="Ops", roles=["bhiv-admin"])
    )
    assert resp.status_code == 200

    publish = client.post(
        f"/canonical-repository/documents/{doc['id']}/versions",
        json={"content": "admin write", "change_note": "n", "published_by": "Ops"},
        headers=_headers(actor="Ops", roles=["bhiv-admin"]),
    )
    assert publish.status_code == 200


def test_custom_access_policy_is_stored_and_enforced(client):
    resp = _register(
        client,
        category="bcaes_vol_7",
        access_policy={"read_roles": ["tantra-runtime"], "write_roles": ["gc-team"]},
        headers=_headers(actor="GCOwner", roles=["gc-team"]),
    )
    body = resp.json()
    assert body["access_policy"]["read_roles"] == ["tantra-runtime"]
    assert body["access_policy"]["write_roles"] == ["gc-team"]

    # ecosystem-reader (the default read role) does NOT satisfy this
    # document's custom read_roles ("tantra-runtime").
    denied = client.get(
        f"/canonical-repository/documents/{body['id']}", headers=_headers(actor="Someone")
    )
    assert denied.status_code == 403

    allowed = client.get(
        f"/canonical-repository/documents/{body['id']}",
        headers=_headers(actor="TantraBot", roles=["tantra-runtime"]),
    )
    assert allowed.status_code == 200
