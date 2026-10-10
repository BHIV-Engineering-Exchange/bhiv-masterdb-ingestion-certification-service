import shutil

import pytest

from services.knowledge_object_service import KnowledgeObjectService
from services.package_registry_service import PackageNotFoundError, PackageRegistryService
from services.retrieval_readiness_service import RetrievalReadinessService
from services.runtime_discovery_service import RuntimeDiscoveryService
from services.tantra_interface_service import (
    CertificationStatusNotFoundError,
    TantraInterfaceService,
)

DIRS = [
    "test_tantra_registry_store",
    "test_tantra_kobj_store",
    "test_tantra_retrieval_store",
]


@pytest.fixture
def tantra():
    for d in DIRS:
        shutil.rmtree(d, ignore_errors=True)
    registry = PackageRegistryService(store_dir=DIRS[0])
    kobj = KnowledgeObjectService(registry=registry, store_dir=DIRS[1])
    retrieval = RetrievalReadinessService(
        registry=registry, knowledge_object_service=kobj, store_dir=DIRS[2]
    )
    discovery = RuntimeDiscoveryService(registry=registry)
    service = TantraInterfaceService(
        registry=registry,
        knowledge_object_service=kobj,
        retrieval_readiness_service=retrieval,
        discovery_service=discovery,
    )
    yield service
    for d in DIRS:
        shutil.rmtree(d, ignore_errors=True)


def test_register_dataset(tantra):
    package = tantra.register_dataset(
        dataset_id="BHIV-DS-MARITIME-AIS-LIVE-001",
        dataset_version="1.0",
        schema_version="1.0",
        board="maritime",
        medium="ais",
        language="en",
        owner="nupur",
    )
    assert package.dataset_id == "BHIV-DS-MARITIME-AIS-LIVE-001"
    assert package.status.value == "REGISTERED"


def test_discover_packages_matches_registration(tantra):
    tantra.register_dataset(
        dataset_id="ds-1",
        dataset_version="1.0",
        schema_version="1.0",
        board="maritime",
        medium="ais",
        language="en",
        owner="nupur",
    )
    results = tantra.discover_packages(board="maritime")
    ds_ids = [r["dataset_id"] for r in results]
    assert "ds-1" in ds_ids


def test_runtime_package_lookup_bundles_lineage_and_retrieval(tantra):
    package = tantra.register_dataset(
        dataset_id="ds-2",
        dataset_version="1.0",
        schema_version="1.0",
        board="maritime",
        medium="ais",
        language="en",
        owner="nupur",
    )
    bundle = tantra.runtime_package_lookup(package.package_id)
    assert bundle["package"]["package_id"] == package.package_id
    assert "lineage" in bundle
    assert "retrieval_readiness" in bundle
    assert bundle["certification_status"] is None


def test_runtime_package_lookup_missing_package_raises(tantra):
    with pytest.raises(PackageNotFoundError):
        tantra.runtime_package_lookup("pkg-does-not-exist")


def test_certification_status_missing_raises(tantra):
    with pytest.raises(CertificationStatusNotFoundError):
        tantra.certification_status("dataset-with-no-report")
