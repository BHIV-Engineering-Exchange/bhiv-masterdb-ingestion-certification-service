from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from models import CertificationState, PackageStatus, RetrievalStatus
from services.artifact_store import ArtifactStore
from services.certification_service import CertificationService
from services.knowledge_object_service import KnowledgeObjectService, LineageValidationError
from services.package_registry_service import (
    InvalidTransitionError,
    PackageAlreadyExistsError,
    PackageNotFoundError,
    PackageRegistryService,
)
from services.report_service import ReportService
from services.retrieval_readiness_service import RetrievalReadinessService
from services.validation_service import ValidationService
import main

ROOT = Path(__file__).resolve().parents[1]


def make_test_environment(tmp_path):
    store = ArtifactStore(str(tmp_path / "artifacts"))
    validator = ValidationService(artifact_store=store)
    reporter = ReportService(artifact_store=store)
    registry = PackageRegistryService(store_dir=str(tmp_path / "registry"), report_service=reporter)
    certifier = CertificationService(
        validation_service=validator,
        artifact_store=store,
        package_registry=registry,
    )
    knowledge_objects = KnowledgeObjectService(
        registry=registry, store_dir=str(tmp_path / "knowledge_objects")
    )
    retrieval = RetrievalReadinessService(
        registry=registry,
        knowledge_object_service=knowledge_objects,
        store_dir=str(tmp_path / "retrieval"),
        report_service=reporter,
    )
    return {
        "store": store,
        "validator": validator,
        "reporter": reporter,
        "registry": registry,
        "certifier": certifier,
        "knowledge_objects": knowledge_objects,
        "retrieval": retrieval,
    }


def make_test_client(tmp_path):
    env = make_test_environment(tmp_path)
    main.package_registry_service = env["registry"]
    main.knowledge_object_service = env["knowledge_objects"]
    main.retrieval_readiness_service = env["retrieval"]
    main.certification_service = env["certifier"]
    main.report_service = env["reporter"]
    main.validation_service = env["validator"]
    return TestClient(main.app), env


# ---------------------------------------------------------------------------
# 1. Lifecycle Transitions & Graph Rules
# ---------------------------------------------------------------------------

def test_full_canonical_lifecycle_path(tmp_path):
    env = make_test_environment(tmp_path)
    reg = env["registry"]

    pkg = reg.register(
        dataset_id="ds-lifecycle-001",
        dataset_version="1.0.0",
        schema_version="1.0.0",
        board="maritime",
        medium="api",
        language="en",
        owner="kavy",
    )
    assert pkg.status == PackageStatus.REGISTERED

    # REGISTERED -> INGESTED -> VALIDATED -> VERIFIED -> CERTIFIED -> RETRIEVAL_READY -> DEPRECATED -> ARCHIVED
    transitions = [
        (PackageStatus.INGESTED, "Ingestion complete"),
        (PackageStatus.VALIDATED, "Validation complete"),
        (PackageStatus.VERIFIED, "Verification complete"),
        (PackageStatus.CERTIFIED, "Certification complete"),
        (PackageStatus.RETRIEVAL_READY, "Ready for retrieval"),
        (PackageStatus.DEPRECATED, "Deprecated by owner"),
        (PackageStatus.ARCHIVED, "Archived for retention"),
    ]
    for target_status, reason in transitions:
        pkg = reg.promote(pkg.package_id, target_status, actor="tester", reason=reason)
        assert pkg.status == target_status

    assert pkg.status == PackageStatus.ARCHIVED
    assert len(pkg.history) == 8  # 1 root + 7 promotions

    # Replay consistency
    replayed = reg.replay(pkg.package_id)
    assert replayed == PackageStatus.ARCHIVED

    # Audit completeness
    audit = reg.audit_completeness(pkg.package_id)
    assert audit["complete"] is True
    assert audit["replay_consistent"] is True
    assert not audit["issues"]


def test_active_states_can_directly_deprecate(tmp_path):
    env = make_test_environment(tmp_path)
    reg = env["registry"]

    # Each active state can directly jump to DEPRECATED
    active_steps = [
        [],  # REGISTERED
        [PackageStatus.INGESTED],
        [PackageStatus.INGESTED, PackageStatus.VALIDATED],
        [PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED],
        [PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED],
        [PackageStatus.INGESTED, PackageStatus.VALIDATED, PackageStatus.VERIFIED, PackageStatus.CERTIFIED, PackageStatus.RETRIEVAL_READY],
    ]
    for idx, steps in enumerate(active_steps):
        pkg = reg.register(
            dataset_id=f"ds-deprecate-{idx}",
            dataset_version="1.0.0",
            schema_version="1.0.0",
            board="test",
            medium="test",
            language="en",
            owner="tester",
        )
        for s in steps:
            pkg = reg.promote(pkg.package_id, s, actor="tester", reason="step")
        # Direct deprecation
        pkg = reg.deprecate(pkg.package_id, actor="tester", reason="immediate withdrawal")
        assert pkg.status == PackageStatus.DEPRECATED
        assert reg.replay(pkg.package_id) == PackageStatus.DEPRECATED


def test_invalid_lifecycle_transitions_rejected(tmp_path):
    env = make_test_environment(tmp_path)
    reg = env["registry"]

    pkg = reg.register(
        dataset_id="ds-invalid-001",
        dataset_version="1.0.0",
        schema_version="1.0.0",
        board="maritime",
        medium="api",
        language="en",
        owner="kavy",
    )

    # Illegal skip: REGISTERED -> CERTIFIED
    with pytest.raises(InvalidTransitionError) as exc:
        reg.promote(pkg.package_id, PackageStatus.CERTIFIED, actor="tester", reason="illegal skip")
    assert "Cannot transition package" in str(exc.value)
    assert pkg.status == PackageStatus.REGISTERED  # Unmutated

    # Promote to ARCHIVED
    reg.deprecate(pkg.package_id, actor="tester", reason="retire")
    reg.promote(pkg.package_id, PackageStatus.ARCHIVED, actor="tester", reason="archive")
    assert reg.get(pkg.package_id).status == PackageStatus.ARCHIVED

    # Illegal revive: ARCHIVED -> INGESTED
    with pytest.raises(InvalidTransitionError):
        reg.promote(pkg.package_id, PackageStatus.INGESTED, actor="tester", reason="revive")


# ---------------------------------------------------------------------------
# 2. Certification Consistency & Re-certification
# ---------------------------------------------------------------------------

def test_failed_certification_prevents_promotion_to_certified(tmp_path):
    env = make_test_environment(tmp_path)
    certifier = env["certifier"]
    reg = env["registry"]

    # Run certification on a failing dataset -> REJECTED
    report = certifier.certify(
        dataset_id="ds-failing-quality",
        dataset_path=str(ROOT / "datasets" / "sample.csv"),
        metadata_path=str(ROOT / "datasets" / "incomplete_metadata.json"),
    )
    assert report["state"] == "REJECTED"
    assert report["ingestion_decision"]["eligible_for_masterdb"] is False

    # Create package for that dataset and progress to VERIFIED
    pkg = reg.register(
        dataset_id="ds-failing-quality",
        dataset_version="1.0.0",
        schema_version="1.0.0",
        board="test",
        medium="test",
        language="en",
        owner="tester",
    )
    reg.promote(pkg.package_id, PackageStatus.INGESTED, actor="tester", reason="ingest")
    reg.promote(pkg.package_id, PackageStatus.VALIDATED, actor="tester", reason="validate")
    reg.promote(pkg.package_id, PackageStatus.VERIFIED, actor="tester", reason="verify")

    # Attempting to promote to CERTIFIED must be rejected!
    with pytest.raises(InvalidTransitionError) as exc:
        reg.promote(pkg.package_id, PackageStatus.CERTIFIED, actor="tester", reason="certify")
    assert "failed certification (state: REJECTED)" in str(exc.value)
    assert reg.get(pkg.package_id).status == PackageStatus.VERIFIED


def test_recertification_idempotency_does_not_corrupt_audit(tmp_path):
    env = make_test_environment(tmp_path)
    certifier = env["certifier"]

    # First certification -> CERTIFIED
    report1 = certifier.certify(
        dataset_id="ds-idempotent-cert",
        dataset_path=str(ROOT / "datasets" / "certifiable_sample.csv"),
        metadata_path=str(ROOT / "datasets" / "metadata.json"),
    )
    assert report1["state"] == "CERTIFIED"
    trail1 = [r["to_state"] for r in report1["audit_trail"]]
    assert trail1 == ["VALIDATED", "VERIFIED", "CERTIFIED"]

    # Re-certify the same dataset without changes
    report2 = certifier.certify(dataset_id="ds-idempotent-cert")
    assert report2["state"] == "CERTIFIED"
    trail2 = [r["to_state"] for r in report2["audit_trail"]]
    # Must NOT have regressive hops like ["VALIDATED", "VERIFIED", "CERTIFIED", "VERIFIED", "CERTIFIED"]
    assert trail2 == ["VALIDATED", "VERIFIED", "CERTIFIED"]


def test_failed_recertification_deprecates_active_packages(tmp_path):
    env = make_test_environment(tmp_path)
    certifier = env["certifier"]
    reg = env["registry"]

    # First certify clean dataset
    report = certifier.certify(
        dataset_id="ds-active-package",
        dataset_path=str(ROOT / "datasets" / "certifiable_sample.csv"),
        metadata_path=str(ROOT / "datasets" / "metadata.json"),
    )
    assert report["state"] == "CERTIFIED"

    # Register and promote package to CERTIFIED
    pkg = reg.register(
        dataset_id="ds-active-package",
        dataset_version="1.0.0",
        schema_version="1.0.0",
        board="test",
        medium="test",
        language="en",
        owner="tester",
    )
    reg.promote(pkg.package_id, PackageStatus.INGESTED, actor="tester", reason="ingest")
    reg.promote(pkg.package_id, PackageStatus.VALIDATED, actor="tester", reason="validate")
    reg.promote(pkg.package_id, PackageStatus.VERIFIED, actor="tester", reason="verify")
    pkg = reg.promote(pkg.package_id, PackageStatus.CERTIFIED, actor="tester", reason="certify")
    assert pkg.status == PackageStatus.CERTIFIED

    # Now simulate quality degradation on the stored report
    stored_report = env["store"].load("ds-active-package")
    stored_report["risk_flags"] = ["CRITICAL_DATA_DRIFT"]
    env["store"].save("ds-active-package", stored_report)

    # Re-certifying fails -> state becomes REJECTED
    recert_report = certifier.certify(dataset_id="ds-active-package")
    assert recert_report["state"] == "REJECTED"

    # Package must automatically transition to DEPRECATED
    updated_pkg = reg.get(pkg.package_id)
    assert updated_pkg.status == PackageStatus.DEPRECATED


# ---------------------------------------------------------------------------
# 3. Retrieval Readiness Consistency
# ---------------------------------------------------------------------------

def test_retrieval_readiness_states_progression(tmp_path):
    env = make_test_environment(tmp_path)
    reg = env["registry"]
    ko_service = env["knowledge_objects"]
    retrieval = env["retrieval"]

    pkg = reg.register(
        dataset_id="ds-readiness-001",
        dataset_version="1.0.0",
        schema_version="1.0.0",
        board="maritime",
        medium="api",
        language="en",
        owner="kavy",
    )

    # 1. Registered: NOT_RETRIEVABLE
    assert retrieval.assess(pkg.package_id).status == RetrievalStatus.NOT_RETRIEVABLE

    # Progress to CERTIFIED (without lineage) -> PARTIALLY_RETRIEVABLE
    reg.promote(pkg.package_id, PackageStatus.INGESTED, actor="tester", reason="i")
    reg.promote(pkg.package_id, PackageStatus.VALIDATED, actor="tester", reason="v")
    reg.promote(pkg.package_id, PackageStatus.VERIFIED, actor="tester", reason="ver")
    reg.promote(pkg.package_id, PackageStatus.CERTIFIED, actor="tester", reason="cert")

    # Certified but no lineage registered -> PARTIALLY_RETRIEVABLE
    ev = retrieval.assess(pkg.package_id)
    assert ev.status == RetrievalStatus.PARTIALLY_RETRIEVABLE

    # 2. Add lineage -> RETRIEVABLE
    ko_service.register_object(
        package_id=pkg.package_id,
        source_reference="src-demo",
        derivation_path=["raw", "clean"],
    )
    ev = retrieval.assess(pkg.package_id)
    assert ev.status == RetrievalStatus.RETRIEVABLE

    # 3. Promote to RETRIEVAL_READY -> CERTIFIED_RETRIEVABLE
    reg.promote(pkg.package_id, PackageStatus.RETRIEVAL_READY, actor="tester", reason="ready")
    ev = retrieval.assess(pkg.package_id)
    assert ev.status == RetrievalStatus.CERTIFIED_RETRIEVABLE

    # 4. Deprecate -> Drops immediately to NOT_RETRIEVABLE
    reg.deprecate(pkg.package_id, actor="tester", reason="deprecated")
    ev = retrieval.assess(pkg.package_id)
    assert ev.status == RetrievalStatus.NOT_RETRIEVABLE


def test_failed_certification_forces_not_retrievable(tmp_path):
    env = make_test_environment(tmp_path)
    reg = env["registry"]
    ko_service = env["knowledge_objects"]
    retrieval = env["retrieval"]

    pkg = reg.register(
        dataset_id="ds-rejected-cert",
        dataset_version="1.0.0",
        schema_version="1.0.0",
        board="maritime",
        medium="api",
        language="en",
        owner="kavy",
    )
    ko_service.register_object(pkg.package_id, source_reference="src-1")

    # Manually store a REJECTED certification report
    env["store"].save("ds-rejected-cert", {
        "dataset_id": "ds-rejected-cert",
        "state": "REJECTED",
        "ingestion_decision": {"eligible_for_masterdb": False},
    })

    # Even if package status were artificially CERTIFIED, retrieval rule must fail
    raw_pkg = reg.get(pkg.package_id)
    raw_pkg.status = PackageStatus.CERTIFIED
    reg._save(raw_pkg)

    ev = retrieval.assess(pkg.package_id)
    assert ev.status == RetrievalStatus.NOT_RETRIEVABLE
    failed_rule = next(r for r in ev.rules if r.rule == "PACKAGE_CERTIFIED")
    assert failed_rule.passed is False
    assert "failed certification (state: REJECTED)" in failed_rule.detail


# ---------------------------------------------------------------------------
# 4. Identifier Consistency & Constraints
# ---------------------------------------------------------------------------

def test_canonical_package_id_format(tmp_path):
    import re
    env = make_test_environment(tmp_path)
    reg = env["registry"]

    pkg = reg.register(
        dataset_id="ds-format-test",
        dataset_version="1.0.0",
        schema_version="1.0.0",
        board="test",
        medium="test",
        language="en",
        owner="kavy",
    )
    # Canonical assigned format: pkg-[a-f0-9]{12}
    assert re.match(r"^pkg-[a-f0-9]{12}$", pkg.package_id)


def test_duplicate_package_id_registration_returns_409(tmp_path):
    client, env = make_test_client(tmp_path)

    # Register first package with custom package_id
    payload = {
        "package_id": "pkg-111122223333",
        "dataset_id": "ds-dup-test",
        "dataset_version": "1.0.0",
        "schema_version": "1.0.0",
        "board": "test",
        "medium": "test",
        "language": "en",
        "owner": "kavy",
    }
    resp1 = client.post("/packages/register", json=payload)
    assert resp1.status_code == 200

    # Attempt to register duplicate package_id -> 409
    resp2 = client.post("/packages/register", json=payload)
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["error"]["message"]


def test_unknown_identifiers_return_404(tmp_path):
    client, _ = make_test_client(tmp_path)

    assert client.get("/packages/pkg-nonexistent").status_code == 404
    assert client.get("/packages/pkg-nonexistent/history").status_code == 404
    assert client.get("/packages/pkg-nonexistent/replay").status_code == 404
    assert client.get("/packages/pkg-nonexistent/audit").status_code == 404
    assert client.get("/packages/pkg-nonexistent/retrieval").status_code == 404
    assert client.get("/tantra/packages/pkg-nonexistent/retrieval-readiness").status_code == 404
    assert client.get("/tantra/packages/pkg-nonexistent/runtime").status_code == 404


def test_empty_identifier_fields_rejected(tmp_path):
    client, _ = make_test_client(tmp_path)

    bad_payload = {
        "dataset_id": "",
        "dataset_version": "1.0.0",
        "schema_version": "1.0.0",
        "board": "test",
        "medium": "test",
        "language": "en",
        "owner": "kavy",
    }
    resp = client.post("/packages/register", json=bad_payload)
    assert resp.status_code in (400, 422)


def test_upload_service_complete_upload_uses_canonical_package_id(tmp_path):
    import re
    from upload.service import UploadService
    from upload.store import UploadStore
    from upload.models import UploadStatus

    store = UploadStore(str(tmp_path / "uploads"))
    service = UploadService(store=store, staging_dir=str(tmp_path / "staging"))

    job = service.initiate_upload(
        filename="test.csv",
        content_type="text/csv",
        file_size=100,
        actor="tester",
        roles=["operator"],
    )
    job.status = UploadStatus.VALIDATED
    store.save(job)

    completed = service.complete_upload(job.upload_id, trigger_validation=False)
    assert completed.status == UploadStatus.REGISTERED
    # Must match canonical pkg-[a-f0-9]{12}, NOT pkg-upl-...
    assert re.match(r"^pkg-[a-f0-9]{12}$", completed.package_id)
