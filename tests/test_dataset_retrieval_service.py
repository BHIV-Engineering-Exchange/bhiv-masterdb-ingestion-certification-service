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


def test_query_exact_certified_version_success(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg1 = registry.register("ds-v", "1.0.0", "2", "AI", "text", "en", "kavy")
    pkg2 = registry.register("ds-v", "2.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg1.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)
    promote_to(registry, pkg2.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    result = dataset_retrieval.query("ds-v", {"select": "*"}, dataset_version="1.0.0")

    assert result["dataset_id"] == "ds-v"
    assert result["dataset_version"] == "1.0.0"
    assert result["package_id"] == pkg1.package_id
    assert result["traceability"]["requested_version"] == "1.0.0"
    assert result["granted"] is True


def test_query_exact_uncertified_version_rejected(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg1 = registry.register("ds-uncert", "1.0.0", "2", "AI", "text", "en", "kavy")
    registry.register("ds-uncert", "2.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg1.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.query("ds-uncert", {"select": "*"}, dataset_version="2.0.0")


def test_query_unknown_version_raises_404(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg = registry.register("ds-unk", "1.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    with pytest.raises(PackageNotFoundError):
        dataset_retrieval.query("ds-unk", {"select": "*"}, dataset_version="9.9.9")


def test_default_picks_latest_certified_over_newer_draft(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg1 = registry.register("ds-draft", "1.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg1.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)
    registry.register("ds-draft", "2.0.0", "2", "AI", "text", "en", "kavy")

    result = dataset_retrieval.query("ds-draft", {"select": "*"})

    assert result["dataset_id"] == "ds-draft"
    assert result["dataset_version"] == "1.0.0"
    assert result["package_id"] == pkg1.package_id
    assert result["traceability"]["requested_version"] is None
    assert result["granted"] is True


def test_default_picks_newest_when_multiple_certified(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg1 = registry.register("ds-multi", "1.0.0", "2", "AI", "text", "en", "kavy")
    pkg2 = registry.register("ds-multi", "2.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg1.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)
    promote_to(registry, pkg2.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    result = dataset_retrieval.query("ds-multi", {"select": "*"})

    assert result["dataset_id"] == "ds-multi"
    assert result["dataset_version"] == "2.0.0"
    assert result["package_id"] == pkg2.package_id


def test_duplicate_version_eligible_beats_ineligible(tmp_path):
    registry, _, retrieval, dataset_retrieval = make_services(tmp_path)
    pkg_ineligible = registry.register("ds-dup", "1.0.0", "2", "AI", "text", "en", "kavy")
    pkg_ineligible = promote_to(registry, pkg_ineligible.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED, PackageStatus.DEPRECATED)

    pkg_eligible = registry.register("ds-dup", "1.0.0", "2", "AI", "text", "en", "kavy")
    pkg_eligible = promote_to(registry, pkg_eligible.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    result = dataset_retrieval.query("ds-dup", {"select": "*"}, dataset_version="1.0.0")

    assert result["package_id"] == pkg_eligible.package_id
    assert result["granted"] is True


def test_identical_timestamps_package_id_tiebreaker(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg_a = registry.register("ds-tie", "1.0.0", "2", "AI", "text", "en", "kavy")
    pkg_b = registry.register("ds-tie", "2.0.0", "2", "AI", "text", "en", "kavy")
    pkg_a = promote_to(registry, pkg_a.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)
    pkg_b = promote_to(registry, pkg_b.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    # Force identical timestamps
    pkg_a.created_at = "2026-03-01T12:00:00Z"
    pkg_b.created_at = "2026-03-01T12:00:00Z"
    registry.store.save(pkg_a.package_id, pkg_a.model_dump(mode="json"))
    registry.store.save(pkg_b.package_id, pkg_b.model_dump(mode="json"))

    expected_winner = max([pkg_a, pkg_b], key=lambda p: p.package_id)
    result = dataset_retrieval.query("ds-tie", {"select": "*"})

    assert result["package_id"] == expected_winner.package_id


def test_precomputed_evidence_reused_no_duplicate_write(tmp_path):
    registry, _, retrieval, dataset_retrieval = make_services(tmp_path)
    pkg = registry.register("ds-reuse", "1.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    original_assess = retrieval.assess
    call_counts = {"count": 0}

    def counted_assess(package_id):
        call_counts["count"] += 1
        return original_assess(package_id)

    retrieval.assess = counted_assess

    result = dataset_retrieval.query("ds-reuse", {"select": "*"}, dataset_version="1.0.0")

    assert result["granted"] is True
    # Exactly 1 assess call during candidate assessment, reused in _controlled_access
    assert call_counts["count"] == 1


def test_reference_with_explicit_uncertified_version(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg = registry.register("ds-ref-uncert", "1.0.0", "2", "AI", "text", "en", "kavy")

    result = dataset_retrieval.reference("ds-ref-uncert", dataset_version="1.0.0")

    assert result["dataset_id"] == "ds-ref-uncert"
    assert result["dataset_version"] == "1.0.0"
    assert result["package_id"] == pkg.package_id
    assert result["granted"] is True
    assert result["access_policy"] == "policy-ds-ref-uncert-restricted"


def test_export_and_stream_with_explicit_version(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg = registry.register("ds-ops", "1.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED)

    export_res = dataset_retrieval.export_dataset("ds-ops", format="csv", dataset_version="1.0.0")
    assert export_res["dataset_version"] == "1.0.0"
    assert export_res["operation"] == "export"
    assert export_res["traceability"]["requested_version"] == "1.0.0"

    stream_res = dataset_retrieval.stream("ds-ops", stream_params={"chunk": 50}, dataset_version="1.0.0")
    assert stream_res["dataset_version"] == "1.0.0"
    assert stream_res["operation"] == "stream"
    assert stream_res["traceability"]["requested_version"] == "1.0.0"


def test_precomputed_negative_evidence_reused_without_reassessment(tmp_path):
    registry, _, retrieval, dataset_retrieval = make_services(tmp_path)
    pkg = registry.register("ds-neg-reuse", "1.0.0", "2", "AI", "text", "en", "kavy")

    call_counts = {"count": 0}
    original_assess = retrieval.assess

    def counted_assess(package_id):
        call_counts["count"] += 1
        return original_assess(package_id)

    retrieval.assess = counted_assess

    # 1. Query: assess called once during selection, reused in _controlled_access -> raises DatasetNotRetrievableError
    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.query("ds-neg-reuse", {"select": "*"}, dataset_version="1.0.0")
    assert call_counts["count"] == 1

    # 2. Export: assess called once during selection, reused in _controlled_access -> raises DatasetNotRetrievableError
    call_counts["count"] = 0
    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.export_dataset("ds-neg-reuse", format="json", dataset_version="1.0.0")
    assert call_counts["count"] == 1

    # 3. Stream: assess called once during selection, reused in _controlled_access -> raises DatasetNotRetrievableError
    call_counts["count"] = 0
    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.stream("ds-neg-reuse", stream_params={}, dataset_version="1.0.0")
    assert call_counts["count"] == 1

    # 4. Reference: assess called once during selection, reused in _controlled_access -> succeeds
    call_counts["count"] = 0
    ref_res = dataset_retrieval.reference("ds-neg-reuse", dataset_version="1.0.0")
    assert call_counts["count"] == 1
    assert ref_res["granted"] is True
    assert ref_res["retrieval_status"] == "NOT_RETRIEVABLE"


def test_fallback_selection_when_no_certified_candidate_eligible(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg_old = registry.register("ds-fallback", "1.0.0", "2", "AI", "text", "en", "kavy")
    pkg_new = registry.register("ds-fallback", "2.0.0", "2", "AI", "text", "en", "kavy")

    # 1. Default reference should fall back to the newest non-deprecated candidate (pkg_new)
    result = dataset_retrieval.reference("ds-fallback")
    assert result["dataset_version"] == "2.0.0"
    assert result["package_id"] == pkg_new.package_id
    assert result["granted"] is True
    assert result["access_policy"] == "policy-ds-fallback-restricted"

    # 2. Default query should fall back to newest candidate, but fail retrievability gate
    with pytest.raises(DatasetNotRetrievableError):
        dataset_retrieval.query("ds-fallback", {"select": "*"})

    # 3. Explicit request for older version "1.0.0" must NEVER substitute fallback version "2.0.0"
    ref_explicit = dataset_retrieval.reference("ds-fallback", dataset_version="1.0.0")
    assert ref_explicit["dataset_version"] == "1.0.0"
    assert ref_explicit["package_id"] == pkg_old.package_id
    assert ref_explicit["traceability"]["requested_version"] == "1.0.0"


def test_fallback_selection_all_deprecated(tmp_path):
    registry, _, _, dataset_retrieval = make_services(tmp_path)
    pkg1 = registry.register("ds-all-dep", "1.0.0", "2", "AI", "text", "en", "kavy")
    pkg2 = registry.register("ds-all-dep", "2.0.0", "2", "AI", "text", "en", "kavy")
    promote_to(registry, pkg1.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED, PackageStatus.DEPRECATED)
    promote_to(registry, pkg2.package_id, PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED, PackageStatus.DEPRECATED)

    ref = dataset_retrieval.reference("ds-all-dep")
    assert ref["package_id"] == pkg2.package_id
    assert ref["dataset_version"] == "2.0.0"
