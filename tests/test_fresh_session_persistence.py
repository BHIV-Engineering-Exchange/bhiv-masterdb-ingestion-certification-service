from pathlib import Path
import pytest

from database_targets.models import IngestionFormat, TargetDatabase
from database_targets.service import DatabaseRouterService
from security.path_resolution import register_allowed_root
from services.artifact_store import ArtifactStore
from services.certification_service import CertificationService
from services.sql_artifact_store import SqlArtifactStore
from services.validation_service import ValidationService

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_session_persistence_retrieval(tmp_path):
    # 1. Setup isolated directories & SQL store
    db_file = tmp_path / "test_target_store.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    store_dir = tmp_path / "ingestion_jobs"
    reports_dir = tmp_path / "reports"
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    register_allowed_root(datasets_dir)

    # 2. Write physical dataset CSV with real records matching certification requirements
    dataset_id = "fresh_session_dataset"
    ds_csv = datasets_dir / f"{dataset_id}.csv"
    sample_src = ROOT / "datasets" / "certifiable_sample.csv"
    ds_csv.write_bytes(sample_src.read_bytes())

    # 3. Create Session A store & router service
    sql_store_a = SqlArtifactStore(db_url, store_name="reports")
    validator_a = ValidationService(artifact_store=sql_store_a)
    certifier_a = CertificationService(validation_service=validator_a, artifact_store=sql_store_a)
    certifier_a.certify(
        dataset_id=dataset_id,
        dataset_path=str(ds_csv),
        metadata_path=str(ROOT / "datasets" / "metadata.json"),
    )

    router_a = DatabaseRouterService(
        certification_artifact_store=sql_store_a,
        store_dir=str(store_dir),
        target_store=sql_store_a,
        dataset_dir=str(datasets_dir),
    )

    # 4. Perform Ingestion
    job = router_a.ingest(
        dataset_id=dataset_id,
        target_database=TargetDatabase.RELATIONAL_DB,
        source_format=IngestionFormat.CSV,
        actor="kavy",
        roles=["ingest:relationaldb"],
    )
    assert job.status.value == "PERSISTED"

    # 5. Simulate Session Closure: destroy Session A objects
    del router_a
    del certifier_a
    del validator_a
    del sql_store_a

    # 6. Create NEW Session B store connecting to the same physical database file
    sql_store_b = SqlArtifactStore(db_url, store_name="reports")
    router_b = DatabaseRouterService(
        certification_artifact_store=sql_store_b,
        store_dir=str(store_dir),
        target_store=sql_store_b,
        dataset_dir=str(datasets_dir),
    )

    # 7. Retrieve target summary and records from Session B
    summary = router_b.get_target_dataset(TargetDatabase.RELATIONAL_DB, dataset_id)
    assert summary is not None
    assert summary["dataset_id"] == dataset_id
    assert summary["target_database"] == "RelationalDB"
    assert summary["record_count"] == 5
    assert summary["status"] == "PERSISTED"

    records = router_b.list_target_records(TargetDatabase.RELATIONAL_DB, dataset_id, limit=10)
    assert len(records) == 5
    assert records[0] == {"id": 1, "name": "John Doe", "age": 25, "email": "john@gmail.com"}
    assert records[1] == {"id": 2, "name": "Alice Smith", "age": 30, "email": "alice@gmail.com"}
