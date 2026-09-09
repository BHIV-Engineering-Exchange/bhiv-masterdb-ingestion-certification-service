from pathlib import Path

import pytest

from database_targets.models import IngestionFormat, IngestionJobStatus, TargetDatabase
from database_targets.service import DatabaseRouterService, UnknownDatabaseError
from services.artifact_store import ArtifactStore
from services.certification_service import CertificationService
from services.validation_service import ValidationService

ROOT = Path(__file__).resolve().parents[1]


def make_router(tmp_path):
    cert_store = ArtifactStore(str(tmp_path / "reports"))
    validator = ValidationService(artifact_store=cert_store)
    certifier = CertificationService(validation_service=validator, artifact_store=cert_store)
    router = DatabaseRouterService(
        certification_artifact_store=cert_store,
        store_dir=str(tmp_path / "ingestion_jobs"),
    )
    return router, certifier


def certify_sample(certifier, dataset_id="certifiable"):
    return certifier.certify(
        dataset_id=dataset_id,
        dataset_path=str(ROOT / "datasets" / "certifiable_sample.csv"),
        metadata_path=str(ROOT / "datasets" / "metadata.json"),
    )


def test_list_databases_returns_all_eight_targets(tmp_path):
    router, _ = make_router(tmp_path)
    keys = {db.key for db in router.list_databases()}
    assert keys == set(TargetDatabase)


def test_get_unknown_database_raises(tmp_path):
    router, _ = make_router(tmp_path)
    with pytest.raises(UnknownDatabaseError):
        router.get_database("NotARealDB")


def test_ingest_rejected_without_required_role(tmp_path):
    router, certifier = make_router(tmp_path)
    certify_sample(certifier)

    job = router.ingest(
        dataset_id="certifiable",
        target_database=TargetDatabase.RELATIONAL_DB,
        source_format=IngestionFormat.CSV,
        actor="rahil",
        roles=["dashboard-viewer"],
    )
    assert job.status == IngestionJobStatus.REJECTED
    assert "not authorized" in job.rejection_reason
    assert job.steps[0].step == "RBAC_CHECK"
    assert job.steps[0].passed is False


def test_ingest_rejected_for_unsupported_format(tmp_path):
    router, certifier = make_router(tmp_path)
    certify_sample(certifier)

    job = router.ingest(
        dataset_id="certifiable",
        target_database=TargetDatabase.VECTOR_DB,
        source_format=IngestionFormat.PDF,
        actor="kavy",
        roles=["ingest:vectordb"],
    )
    assert job.status == IngestionJobStatus.REJECTED
    assert "not supported by VectorDB" in job.rejection_reason


def test_ingest_rejected_when_not_certified(tmp_path):
    router, validator_service = make_router(tmp_path)
    # No certification run at all — dataset unknown to the certification store.
    job = router.ingest(
        dataset_id="never-certified",
        target_database=TargetDatabase.RELATIONAL_DB,
        source_format=IngestionFormat.CSV,
        actor="kavy",
        roles=["ingest:relationaldb"],
    )
    assert job.status == IngestionJobStatus.REJECTED
    assert "not CERTIFIED" in job.rejection_reason


def test_ingest_succeeds_for_certified_dataset_with_role(tmp_path):
    router, certifier = make_router(tmp_path)
    certify_sample(certifier)

    job = router.ingest(
        dataset_id="certifiable",
        target_database=TargetDatabase.RELATIONAL_DB,
        source_format=IngestionFormat.CSV,
        actor="kavy",
        roles=["ingest:relationaldb"],
    )
    assert job.status == IngestionJobStatus.PERSISTED
    assert job.certification_state == "CERTIFIED"
    assert [s.step for s in job.steps] == ["RBAC_CHECK", "FORMAT_CHECK", "CERTIFICATION_GATE", "ROUTED"]
    assert all(s.passed for s in job.steps)

    fetched = router.get_job(job.job_id)
    assert fetched.job_id == job.job_id


def test_admin_role_bypasses_database_specific_role(tmp_path):
    router, certifier = make_router(tmp_path)
    certify_sample(certifier)

    job = router.ingest(
        dataset_id="certifiable",
        target_database=TargetDatabase.ARCHIVE_DB,
        source_format=IngestionFormat.CSV,
        actor="ops",
        roles=["bhiv-admin"],
    )
    assert job.status == IngestionJobStatus.PERSISTED


def test_list_jobs_filters_by_dataset_and_status(tmp_path):
    router, certifier = make_router(tmp_path)
    certify_sample(certifier, "ds-a")
    certify_sample(certifier, "ds-b")

    router.ingest("ds-a", TargetDatabase.RELATIONAL_DB, IngestionFormat.CSV, "kavy", ["ingest:relationaldb"])
    router.ingest("ds-b", TargetDatabase.RELATIONAL_DB, IngestionFormat.CSV, "kavy", ["ingest:relationaldb"])
    router.ingest("ds-a", TargetDatabase.VECTOR_DB, IngestionFormat.CSV, "rahil", [])

    ds_a_jobs = router.list_jobs(dataset_id="ds-a")
    assert len(ds_a_jobs) == 2

    rejected_jobs = router.list_jobs(status=IngestionJobStatus.REJECTED)
    assert len(rejected_jobs) == 1
    assert rejected_jobs[0].actor == "rahil"
