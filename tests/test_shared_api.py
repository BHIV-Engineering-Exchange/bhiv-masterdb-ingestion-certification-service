from fastapi.testclient import TestClient

import main


def make_client(tmp_path):
    for name, service in main.shared_service_registry.items():
        safe_name = name.replace("-", "_")
        service.store.reports_dir = tmp_path / f"shared_{safe_name}"
        service.store.reports_dir.mkdir(parents=True, exist_ok=True)
    token, _ = main.auth_service.issue_token("kavy", ["bhiv-admin", "operator"])
    return TestClient(main.app, headers={"Authorization": f"Bearer {token}"})


# -- Phase 1: registry ------------------------------------------------------


def test_list_shared_data_registry(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/shared/registry")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 15
    names = {entry["name"] for entry in body["datasets"]}
    assert "identity" in names
    assert "audit_events" in names


def test_get_single_dataset_definition(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/shared/registry/identity")
    assert response.status_code == 200
    assert response.json()["name"] == "identity"


def test_get_unknown_dataset_definition_returns_404(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/shared/registry/does-not-exist")
    assert response.status_code == 404


# -- Phase 2: contracts -------------------------------------------------------


def test_list_shared_service_contracts(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/shared/contracts")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 6
    assert "identity" in body["contracts"]


def test_get_single_contract(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/shared/contracts/authentication")
    assert response.status_code == 200
    assert response.json()["service"] == "authentication"
    assert "ownership_boundary" in response.json()


# -- Phase 4: runtime API -- register / update / deprecate / get ------------


def test_register_get_update_lifecycle_for_identity(tmp_path):
    client = make_client(tmp_path)

    register_response = client.post(
        "/shared/identity/register",
        json={
            "record_id": "id-api-1",
            "payload": {"display_name": "Kavy"},
            "actor": "kavy",
            "reason": "initial identity record",
        },
    )
    assert register_response.status_code == 200
    assert register_response.json()["version"] == 1

    get_response = client.get("/shared/identity/id-api-1")
    assert get_response.status_code == 200
    assert get_response.json()["payload"]["display_name"] == "Kavy"

    update_response = client.put(
        "/shared/identity/id-api-1",
        json={"payload": {"display_name": "Kavy S"}, "actor": "kavy", "reason": "name update"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["version"] == 2

    list_response = client.get("/shared/identity")
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1


def test_register_missing_required_field_returns_400(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/shared/configuration/register",
        json={"record_id": "cfg-api-1", "payload": {"key": "only_key"}, "actor": "kavy", "reason": "bad"},
    )
    assert response.status_code == 400


def test_register_duplicate_record_returns_409(tmp_path):
    client = make_client(tmp_path)
    payload = {
        "record_id": "cfg-api-2",
        "payload": {"key": "max_retries", "value": 3},
        "actor": "kavy",
        "reason": "init",
    }
    first = client.post("/shared/configuration/register", json=payload)
    assert first.status_code == 200
    second = client.post("/shared/configuration/register", json=payload)
    assert second.status_code == 409


def test_get_unknown_record_returns_404(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/shared/identity/does-not-exist")
    assert response.status_code == 404


def test_unknown_service_name_returns_404(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/shared/not-a-real-service")
    assert response.status_code == 404


def test_deprecate_then_update_returns_400(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/shared/identity/register",
        json={"record_id": "id-api-2", "payload": {"display_name": "Temp"}, "actor": "kavy", "reason": "init"},
    )
    deprecate_response = client.post(
        "/shared/identity/id-api-2/deprecate", json={"actor": "kavy", "reason": "retired"}
    )
    assert deprecate_response.status_code == 200
    assert deprecate_response.json()["deprecated"] is True

    blocked_update = client.put(
        "/shared/identity/id-api-2",
        json={"payload": {"display_name": "Should Fail"}, "actor": "kavy", "reason": "nope"},
    )
    assert blocked_update.status_code == 400


# -- Phase 5: replay consistency, audit history ------------------------------


def test_replay_and_history_endpoints(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/shared/notifications/register",
        json={
            "record_id": "notif-api-1",
            "payload": {"channel": "email", "template": "welcome"},
            "actor": "kavy",
            "reason": "init",
        },
    )
    client.put(
        "/shared/notifications/notif-api-1",
        json={"payload": {"channel": "sms", "template": "welcome"}, "actor": "kavy", "reason": "switch channel"},
    )

    history_response = client.get("/shared/notifications/notif-api-1/history")
    assert history_response.status_code == 200
    assert len(history_response.json()["history"]) == 2

    replay_response = client.get("/shared/notifications/notif-api-1/replay")
    assert replay_response.status_code == 200
    assert replay_response.json()["replay_consistent"] is True


# -- Phase 5: cross-service dataset retrieval / missing dependency ----------


def test_resolve_cross_service_dependency_via_api(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/shared/identity/register",
        json={"record_id": "id-api-3", "payload": {"display_name": "Org Owner"}, "actor": "kavy", "reason": "init"},
    )
    client.post(
        "/shared/organizations/register",
        json={
            "record_id": "org-api-1",
            "payload": {"name": "BHIV", "owner_identity_id": "id-api-3"},
            "actor": "kavy",
            "reason": "init",
        },
    )

    resolve_response = client.get("/shared/organizations/org-api-1/resolve")
    assert resolve_response.status_code == 200
    body = resolve_response.json()
    assert body["fully_resolved"] is True
    assert body["resolved_dependencies"]["owner_identity_id"]["record_id"] == "id-api-3"


def test_resolve_missing_cross_service_dependency_via_api(tmp_path):
    client = make_client(tmp_path)
    client.post(
        "/shared/organizations/register",
        json={
            "record_id": "org-api-2",
            "payload": {"name": "Ghost Org", "owner_identity_id": "id-ghost"},
            "actor": "kavy",
            "reason": "init",
        },
    )
    resolve_response = client.get("/shared/organizations/org-api-2/resolve")
    assert resolve_response.status_code == 200
    body = resolve_response.json()
    assert body["fully_resolved"] is False
    assert "id-ghost" in body["missing_dependencies"][0]


# -- Phase 5: version compatibility -------------------------------------------


def test_version_compatibility_endpoint(tmp_path):
    client = make_client(tmp_path)
    exact = client.get("/shared/version-compatibility", params={"local_version": "1.0", "remote_version": "1.0"})
    assert exact.status_code == 200
    assert exact.json()["compatible"] is True

    mismatch = client.get("/shared/version-compatibility", params={"local_version": "1.0", "remote_version": "2.0"})
    assert mismatch.status_code == 200
    assert mismatch.json()["compatible"] is False
