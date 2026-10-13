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

import main


import os

TEST_AUTH_PASSWORD = "test-auth-password"
TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture(autouse=True)
def _ensure_test_auth_env(monkeypatch):
    if not (
        os.environ.get("AUTH_PASSWORD")
        or os.environ.get("MASTERDB_AUTH_PASSWORD")
    ):
        monkeypatch.setenv("AUTH_PASSWORD", TEST_AUTH_PASSWORD)
    if not os.environ.get("ADMIN_PASSWORD"):
        monkeypatch.setenv("ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    main.rate_limiter.reset()
    yield


import shutil
from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_capability_registry(tmp_path):
    for store_dir in ["capability_store", "source_store", "registry_store"]:
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
    main.geospatial_connector.source_registry = src_registry
    main.geospatial_connector.package_registry = pkg_registry
    main.geospatial_connector.capability_registry = cap_service
    yield
    shutil.rmtree(temp_dir, ignore_errors=True)
