import pytest

from models import PackageStatus
from services.dataset_retrieval_service import (
    DatasetAccessDeniedError,
    DatasetNotRetrievableError,
    DatasetRetrievalService,
)
from services.knowledge_object_service import KnowledgeObjectService
from services.mdu_contract_adapter import MDUContractAdapter
from services.package_registry_service import PackageNotFoundError, PackageRegistryService
from services.retrieval_readiness_service import RetrievalReadinessService


def make_services(tmp_path):
    registry = PackageRegistryService(store_dir=str(tmp_path / "registry"))
    knowledge_objects = KnowledgeObjectService(
        registry=registry, store_dir=str(tmp_path / "knowledge_objects")
    )
    retrieval = RetrievalReadinessService(
        registry=registry,
        knowledge_object_service=knowledge_objects,
        store_dir=str(tmp_path / "retrieval_evidence"),
    )
    mdu_adapter = MDUContractAdapter()
    dataset_retrieval = DatasetRetrievalService(
        registry=registry,
        knowledge_object_service=knowledge_objects,
        retrieval_readiness_service=retrieval,
        mdu_adapter=mdu_adapter,
    )
    return registry, knowledge_objects, retrieval, dataset_retrieval


def register_package(registry, dataset_id="ds-1"):
    return registry.register(
        dataset_id=dataset_id,
        dataset_version="1.0.0",
        schema_version="2",
        board="AI",
        medium="text",
        language="en",
        owner="kavy",
    )


def promote_to(registry, package_id, *statuses):
    package = None
    for status in statuses:
        package = registry.promote(package_id, status, actor="pipeline", reason="progressing")
    return package


def test_list_datasets_empty(tmp_path):
    _, _, _, dataset_retrieval = make_services(tmp_path)
    assert dataset_retrieval.list_datasets() == []


def test_list_datasets_returns_summaries(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    register_package(registry, "ds-1")
    register_package(registry, "ds-2")

    datasets = dataset_retrieval.list_datasets()

    assert len(datasets) == 2
    ids = {d["dataset_id"] for d in datasets}
    assert ids == {"ds-1", "ds-2"}


def test_get_dataset_found(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    package = register_package(registry, "ds-1")

    result = dataset_retrieval.get_dataset("ds-1")

    assert result["dataset_id"] == "ds-1"
    assert result["package_id"] == package.package_id
    assert result["status"] == PackageStatus.REGISTERED.value


def test_get_dataset_not_found(tmp_path):
    _, _, _, dataset_retrieval = make_services(tmp_path)
    with pytest.raises(PackageNotFoundError):
        dataset_retrieval.get_dataset("nonexistent")


def test_get_dataset_by_package_id(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    package = register_package(registry, "ds-1")

    result = dataset_retrieval.get_dataset_by_package_id(package.package_id)

    assert result["dataset_id"] == "ds-1"


def test_get_dataset_schema_fallback_when_mdu_unavailable(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    register_package(registry, "ds-1")

    result = dataset_retrieval.get_dataset_schema("ds-1")

    assert result["source"] == "registry-declared"
    assert result["dataset_id"] == "ds-1"
    assert result["schema_version"] == "2"
    assert "note" in result


def test_get_dataset_versions_found(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    register_package(registry, "ds-1")
    register_package(registry, "ds-1")

    result = dataset_retrieval.get_dataset_versions("ds-1")

    assert result["dataset_id"] == "ds-1"
    assert result["version_count"] == 2
    assert len(result["versions"]) == 2


def test_get_dataset_versions_not_found(tmp_path):
    _, _, _, dataset_retrieval = make_services(tmp_path)
    with pytest.raises(PackageNotFoundError):
        dataset_retrieval.get_dataset_versions("nonexistent")


def test_get_dataset_provenance(tmp_path):
    registry, knowledge_objects, _, dataset_retrieval = make_services(tmp_path)
    package = register_package(registry, "ds-1")
    knowledge_objects.register_object(
        package_id=package.package_id,
        source_reference="s3://bucket/source.csv",
        derivation_path=["ingest", "clean"],
    )

    result = dataset_retrieval.get_dataset_provenance("ds-1")

    assert result["dataset_id"] == "ds-1"
    assert result["package_id"] == package.package_id
    assert "masterdb_lineage" in result


def test_query_restricted_when_not_certified(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    register_package(registry, "ds-1")

    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.query("ds-1", {"select": "*"})


def test_query_allowed_when_certified(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    package = register_package(registry, "ds-1")
    promote_to(
        registry,
        package.package_id,
        PackageStatus.INGESTED,
        PackageStatus.VALIDATED,
        PackageStatus.VERIFIED,
        PackageStatus.CERTIFIED,
    )

    result = dataset_retrieval.query("ds-1", {"select": "*"})

    assert result["dataset_id"] == "ds-1"
    assert result["operation"] == "query"
    assert result["granted"] is True
    assert "access_location" in result
    assert "governance" in result


def test_export_restricted_when_not_certified(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    register_package(registry, "ds-1")

    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.export_dataset("ds-1", "csv")


def test_stream_restricted_when_not_certified(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    register_package(registry, "ds-1")

    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.stream("ds-1", {"chunk_size": 100})


def test_reference_allowed_for_registered(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    package = register_package(registry, "ds-1")

    result = dataset_retrieval.reference("ds-1")

    assert result["dataset_id"] == "ds-1"
    assert result["operation"] == "reference"
    assert result["granted"] is True


def test_access_denied_for_non_owner_on_restricted(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    package = register_package(registry, "ds-1")
    # Promote to INGESTED but not CERTIFIED -> restricted policy
    promote_to(registry, package.package_id, PackageStatus.INGESTED)

    # reference should work because it's in allowed_operations for restricted
    result = dataset_retrieval.reference("ds-1")
    assert result["granted"] is True

    # query should fail because package is NOT_RETRIEVABLE
    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.query("ds-1", {"select": "*"})
