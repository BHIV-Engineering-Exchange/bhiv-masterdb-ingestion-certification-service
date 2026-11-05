from models import PackageStatus, RetrievalStatus
from services.knowledge_object_service import KnowledgeObjectService
from services.package_registry_service import PackageRegistryService
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
    return registry, knowledge_objects, retrieval


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


def test_freshly_registered_package_is_not_retrievable(tmp_path):
    _, _, retrieval = make_services(tmp_path)
    registry = retrieval.registry
    package = register_package(registry)

    evidence = retrieval.assess(package.package_id)

    assert evidence.status == RetrievalStatus.NOT_RETRIEVABLE
    assert any(not rule.passed for rule in evidence.rules)
    assert evidence.corrective_actions


def test_certified_package_without_lineage_is_partially_retrievable(tmp_path):
    registry, _, retrieval = make_services(tmp_path)
    package = register_package(registry)
    promote_to(
        registry,
        package.package_id,
        PackageStatus.INGESTED,
        PackageStatus.VALIDATED,
        PackageStatus.VERIFIED,
        PackageStatus.CERTIFIED,
    )

    evidence = retrieval.assess(package.package_id)

    assert evidence.status == RetrievalStatus.PARTIALLY_RETRIEVABLE


def test_certified_package_with_lineage_is_retrievable(tmp_path):
    registry, knowledge_objects, retrieval = make_services(tmp_path)
    package = register_package(registry)
    knowledge_objects.register_object(
        package_id=package.package_id, source_reference="s3://bucket/source.csv"
    )
    promote_to(
        registry,
        package.package_id,
        PackageStatus.INGESTED,
        PackageStatus.VALIDATED,
        PackageStatus.VERIFIED,
        PackageStatus.CERTIFIED,
    )

    evidence = retrieval.assess(package.package_id)

    assert evidence.status == RetrievalStatus.RETRIEVABLE
    assert not evidence.corrective_actions


def test_retrieval_ready_package_with_lineage_is_certified_retrievable(tmp_path):
    registry, knowledge_objects, retrieval = make_services(tmp_path)
    package = register_package(registry)
    knowledge_objects.register_object(
        package_id=package.package_id, source_reference="s3://bucket/source.csv"
    )
    promote_to(
        registry,
        package.package_id,
        PackageStatus.INGESTED,
        PackageStatus.VALIDATED,
        PackageStatus.VERIFIED,
        PackageStatus.CERTIFIED,
        PackageStatus.RETRIEVAL_READY,
    )

    evidence = retrieval.assess(package.package_id)

    assert evidence.status == RetrievalStatus.CERTIFIED_RETRIEVABLE


def test_deprecated_package_is_not_retrievable_even_if_previously_certified(tmp_path):
    registry, knowledge_objects, retrieval = make_services(tmp_path)
    package = register_package(registry)
    knowledge_objects.register_object(
        package_id=package.package_id, source_reference="s3://bucket/source.csv"
    )
    promote_to(
        registry,
        package.package_id,
        PackageStatus.INGESTED,
        PackageStatus.VALIDATED,
        PackageStatus.VERIFIED,
        PackageStatus.CERTIFIED,
        PackageStatus.DEPRECATED,
    )

    evidence = retrieval.assess(package.package_id)

    assert evidence.status == RetrievalStatus.NOT_RETRIEVABLE


def test_evidence_is_replayable_from_store(tmp_path):
    registry, _, retrieval = make_services(tmp_path)
    package = register_package(registry)

    retrieval.assess(package.package_id)
    replayed = retrieval.get_latest(package.package_id)

    assert replayed is not None
    assert replayed.status == RetrievalStatus.NOT_RETRIEVABLE
    assert replayed.package_id == package.package_id

def test_retrieval_readiness_evidence_persists_across_instances(tmp_path):
    registry_1, knowledge_objects_1, retrieval_1 = make_services(tmp_path)
    package = register_package(registry_1, dataset_id="ds-evidence-persist")
    knowledge_objects_1.register_object(
        package_id=package.package_id, source_reference="s3://bucket/source.csv"
    )
    promote_to(
        registry_1,
        package.package_id,
        PackageStatus.INGESTED,
        PackageStatus.VALIDATED,
        PackageStatus.VERIFIED,
        PackageStatus.CERTIFIED,
    )

    # Initial assessment on instance 1 (status: RETRIEVABLE)
    evidence_1 = retrieval_1.assess(package.package_id)
    assert evidence_1.status == RetrievalStatus.RETRIEVABLE
    assert len(evidence_1.rules) > 0

    # Simulate process restart: discard instance 1 and construct fresh instance 2 against the same directory
    del retrieval_1
    del knowledge_objects_1
    del registry_1

    registry_2, _, retrieval_2 = make_services(tmp_path)

    # Verify latest evidence artifact reloads cleanly on fresh instance without re-running assess
    reloaded = retrieval_2.get_latest(package.package_id)
    assert reloaded is not None
    assert reloaded.package_id == package.package_id
    assert reloaded.status == RetrievalStatus.RETRIEVABLE
    assert len(reloaded.rules) == len(evidence_1.rules)
    assert reloaded.corrective_actions == evidence_1.corrective_actions
