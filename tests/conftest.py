"""
Session-wide test fixtures.

`main.app` is a module-level singleton reused by every test file's
`TestClient(main.app)` — that's fine for the request-handling stack
itself, but any middleware holding its own state (the rate limiter) needs
resetting between tests, or request counts silently accumulate across the
whole suite and tests start failing based on run order/count rather than
their own logic. Individual test files already do this per-service
(`main.bcaes_registry_service = main.BCAESRegistryService()` etc.) for
things they construct; the rate limiter is shared infrastructure every
test touches whether it's testing rate limiting or not, so it gets one
autouse fixture here instead of being repeated in every file.
"""
import pytest

import os
_previous_pytest_marker = os.environ.get("PYTEST_CURRENT_TEST")
os.environ["PYTEST_CURRENT_TEST"] = "pytest collection"
import main
if _previous_pytest_marker is None:
    os.environ.pop("PYTEST_CURRENT_TEST", None)
else:
    os.environ["PYTEST_CURRENT_TEST"] = _previous_pytest_marker


TEST_AUTH_PASSWORD = "test-auth-password"
TEST_ADMIN_PASSWORD = "test-admin-password"
TEST_JWT_SECRET = "test-jwt-secret-key-configured-for-testing-only-32chars!!"
TEST_ALLOWED_ACTORS = (
    "a,actor-a,actor-b,actor_a,actor_b,admin,admin_user,admin-user,bhiv-admin,bhiv_admin,agent-worker,agent_worker,alias-user,alias_user,alice,"
    "arbitrary-unauthorized-actor,arbitrary_unauthorized_actor,attacker,attacker_consumer,attacker-consumer,auth-tester,auth_tester,"
    "authorized-actor,authorized_actor,bharat-mala,bharat-mala-app,bharat_mala,bharat_mala_app,bharat mala,candidate-reviewer,"
    "candidate_reviewer,certifier,consumer-app,consumer_app,contract-tester,contract_tester,cyclone-error-test,cyclone_error_test,"
    "cyclone-test,cyclone_test,data-consumer,data_consumer,data-engineer,data_engineer,delegated-actor,delegated_actor,"
    "domain-tester,domain_tester,entitled-agent,entitled_agent,explicit-consumer,explicit_consumer,fin,gcowner,geo-quest-tester,"
    "geo_quest_tester,grant-owner,grant_owner,impostor-actor,impostor_actor,kavy,kavy-operator,kavy_operator,kavy-engineer,"
    "kavy_engineer,legit-user,legit_user,mallory,marine,marine-analyst,marine_analyst,marine-intel-app,marine_intel_app,"
    "masterdb,masterdb-consumer,masterdb_consumer,masterdb-test-consumer,masterdb_test_consumer,ops,other-actor,other_actor,"
    "outsider,owner,persist-tester,persist_tester,pipeline,prod-actor,prod_actor,radar-test,radar_test,rahil,retrieval-tester,"
    "retrieval_tester,rogue-caller,rogue_caller,satellite-error-test,satellite_error_test,satellite-test,satellite_test,someone,"
    "someoneelse,special-agent,special_agent,super-admin-user,super_admin_user,synthetic-runner,synthetic_runner,tantra-execution,"
    "tantra_execution,tantra-execution-agent,tantra_execution_agent,tantrabot,tasklead,test,test-actor,test_actor,test-admin,"
    "test_admin,test-agent,test_agent,test-app,test_app,test-consumer,test_consumer,test-operator,test_operator,test-runner,"
    "test_runner,test-user,test_user,test-viewer,test_viewer,tester,unauthorized,unentitled-actor,unentitled_actor,"
    "unentitled-direct-consumer,unentitled_direct_consumer,user,user1,valid-consumer,valid_consumer,validator,vana-fin-app,"
    "vana_fin_app,vana-tester,vana_tester,verifier,weather-test,weather_test,worker-actor,worker_actor,worker-bot,worker_bot,"
    "bcaes-editor-user,candidate-viewer,candidate_viewer,gev-viewer,gev_viewer,viewer,domain-tester,domain_tester,tantra-execution,tantra_execution,legit-actor,legit_actor,spoofed-actor,spoofed_actor,victim-account,victim_account"
)


@pytest.fixture(autouse=True)
def _ensure_test_auth_env(monkeypatch):
    from tests.test_identity_fixtures import (
        TEST_RSA_PUBLIC_KEY_PEM,
        TEST_TOKEN_ISSUER,
        get_test_token,
        get_test_auth_headers,
    )
    monkeypatch.setenv("AUTH_JWT_PUBLIC_KEY", TEST_RSA_PUBLIC_KEY_PEM)
    current_issuers = os.environ.get("AUTH_ISSUER", "")
    if TEST_TOKEN_ISSUER not in current_issuers:
        monkeypatch.setenv("AUTH_ISSUER", f"{TEST_TOKEN_ISSUER},{current_issuers}".strip(","))
    if hasattr(main, "auth_service"):
        main.auth_service._public_key_pem = None

    if not (
        os.environ.get("AUTH_PASSWORD")
        or os.environ.get("MASTERDB_AUTH_PASSWORD")
    ):
        monkeypatch.setenv("AUTH_PASSWORD", TEST_AUTH_PASSWORD)
    if not os.environ.get("ADMIN_PASSWORD"):
        monkeypatch.setenv("ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    if not (os.environ.get("ENVIRONMENT") or os.environ.get("APP_ENV") or os.environ.get("MASTERDB_ENV")):
        monkeypatch.setenv("ENVIRONMENT", "test")
    if not (os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET")):
        monkeypatch.setenv("AUTH_JWT_SECRET", TEST_JWT_SECRET)
    if not os.environ.get("AUTH_ALLOWED_ACTORS"):
        monkeypatch.setenv("AUTH_ALLOWED_ACTORS", TEST_ALLOWED_ACTORS)
    # Explicit test actor-to-application entitlements for test consumers (D4 explicit delegation)
    monkeypatch.setenv("AUTH_ENTITLED_APPS_TANTRA_EXECUTION_AGENT", "VALID_CONSUMER")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_GRANT_OWNER", "SHARED_CONSUMER_APP")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_TEST_ACTOR", "consumer-app,unauthorized-app")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_MARINE_ANALYST", "marine-consumer")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_PERSIST_TESTER", "PERSIST_APP")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_GEO_QUEST_TESTER", "BHARAT_MALA_ENV,MARINE_INTELLIGENCE_APP")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_VALID_CONSUMER", "VALID_CONSUMER")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_DATA_CONSUMER", "DATA_CONSUMER")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_MASTERDB_TEST_CONSUMER", "MASTERDB_TEST_CONSUMER")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_FIN", "FIN")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_BHARAT_MALA", "Bharat Mala")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_MARINE", "Marine")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_BHARAT_MALA_APP", "BHARAT_MALA_APP")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_VANA_FIN_APP", "VANA_FIN_APP")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_MARINE_INTEL_APP", "MARINE_INTEL_APP")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_MASTERDB_CONSUMER", "masterdb-consumer")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_VANA_TESTER", "vana-tester")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_TANTRA_EXECUTION", "app-tantra-gated-bridge,app-tantra-original")
    monkeypatch.setenv("AUTH_ENTITLED_APPS_DOMAIN_TESTER", "APP-EDUCATION,APP-ROBOTICS,APP-XR")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    main.rate_limiter.reset()
    yield


import shutil
from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_capability_registry(tmp_path):
    # Only clean up test-generated stores; NEVER touch tracked repository fixtures like source_store
    for store_dir in ["capability_store", "registry_store"]:
        store_path = Path(store_dir)
        if store_path.exists():
            shutil.rmtree(store_path, ignore_errors=True)
    
    import tempfile
    temp_dir = tempfile.mkdtemp(prefix="conftest_stores_")
    sub_dir = Path(temp_dir)
    pkg_store_dir = str(sub_dir / "test_registry_store")
    src_store_dir = str(sub_dir / "test_source_store")
    cap_store_dir = str(sub_dir / "test_capability_store")

    pkg_registry = main.PackageRegistryService(store_dir=pkg_store_dir)
    src_registry = main.SourceRegistryService(store_dir=src_store_dir, audit_emitter=main.production_audit_emitter)
    ret_service = main.DatasetRetrievalService(registry=pkg_registry)
    cap_service = main.CapabilityRegistryService(
        store_dir=cap_store_dir,
        package_registry=pkg_registry,
        retrieval_service=ret_service,
        audit_emitter=main.production_audit_emitter,
        earthquake_observation_service=main.earthquake_observation_service,
    )
    kobj_service = main.KnowledgeObjectService(registry=pkg_registry, store_dir=str(sub_dir / "test_kobj_store"))
    ret_readiness = main.RetrievalReadinessService(registry=pkg_registry, knowledge_object_service=kobj_service, store_dir=str(sub_dir / "test_ret_readiness_store"))
    tantra_service = main.TantraInterfaceService(
        registry=pkg_registry,
        knowledge_object_service=kobj_service,
        retrieval_readiness_service=ret_readiness,
        discovery_service=main.RuntimeDiscoveryService(registry=pkg_registry),
        capability_service=cap_service,
    )

    main.package_registry_service = pkg_registry
    main.source_registry_service = src_registry
    main.capability_registry_service = cap_service
    main.knowledge_object_service = kobj_service
    main.retrieval_readiness_service = ret_readiness
    main.tantra_interface_service = tantra_service
    main.auth_service = main.AuthService()
    main.geospatial_connector.source_registry = src_registry
    main.geospatial_connector.package_registry = pkg_registry
    main.geospatial_connector.capability_registry = cap_service
    yield
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_token():
    from tests.test_identity_fixtures import get_test_token
    return get_test_token


@pytest.fixture
def test_auth_headers():
    from tests.test_identity_fixtures import get_test_auth_headers
    return get_test_auth_headers
