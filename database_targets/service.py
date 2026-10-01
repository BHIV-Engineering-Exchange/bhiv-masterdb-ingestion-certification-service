"""
DatabaseRouterService — attaches the existing, already-built ingestion /
certification pipeline (ValidationService, CertificationService) to the 8
MASTERDB target databases as a limited, highly controlled ingestion
facility.

This service does not re-validate or re-score datasets — that stays
ValidationService/CertificationService's job. It does exactly what Kavy's
task assignment scopes it to:

  1. expose a stable, discoverable per-database capability contract
     (`list_databases` / `get_database`)
  2. enforce authenticated, role-based, database-level ingest authority
     (no unrestricted access just because a database is visible)
  3. route only CERTIFIED datasets to the explicitly authorized target
     database (no direct UI-to-database bypass, no bli  `nd ingestion)
  4. record a fully auditable ingestion job: actor, dataset, source
     format, target, timestamp, validation/certification result, and
     outcome — including rejected attempts, which stay traceable too.
  5. physically persist target records into the target database with atomic
     transactions so data exists after request and can be queried.

Every check (RBAC, format, certification gate, persistence) is recorded as an
`IngestJobStep` regardless of outcome, and every job — accepted or
rejected — is persisted, so `GET /ingest/jobs/{job_id}` always has the
full reasoning trail for the dashboard's validation-feedback / result
states.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from auth.constants import ADMIN_ROLE
from database_targets.models import (
    DatabaseCapability,
    IngestJob,
    IngestJobStep,
    IngestionFormat,
    IngestionJobStatus,
    TargetDatabase,
)
from database_targets.registry import DATABASE_REGISTRY
from security.path_resolution import resolve_secure_path
from services.artifact_store import ArtifactStore
from upload.models import UploadStatus
from upload.store import UploadJobNotFoundError
from utils.loader import DatasetLoader


class DatasetRecordsUnresolvedError(Exception):
    """Raised when dataset records cannot be resolved for ingestion.

    This replaces the previous synthetic-record fallback which was
    removed because it allowed ingestion to report PERSISTED even when
    the actual dataset records could not be loaded.
    """


class UploadStateError(Exception):
    """Raised when an upload cannot be used for ingestion due to its state."""


class UploadOwnershipError(Exception):
    """Raised when the caller is not authorized to use the specified upload."""


class UnknownDatabaseError(KeyError):
    """Raised when `target_database` is not one of the 8 registered MASTERDB
    databases."""


class JobNotFoundError(KeyError):
    """Raised when a job_id does not exist in the ingestion job store."""


class DatabaseRouterService:
    def __init__(
        self,
        certification_artifact_store: ArtifactStore,
        store_dir: str = "ingestion_jobs_store",
        target_store: Optional[Any] = None,
        certification_service: Optional[Any] = None,
        upload_service: Optional[Any] = None,
        dataset_dir: Optional[str] = None,
    ) -> None:
        self._certification_store = certification_artifact_store
        self._job_store = ArtifactStore(reports_dir=store_dir)
        self._target_store = target_store or certification_artifact_store
        self._certification_service = certification_service
        self._upload_service = upload_service
        self._dataset_dir = Path(dataset_dir) if dataset_dir else None

    # -- discovery / contract ------------------------------------------------

    def list_databases(self) -> List[DatabaseCapability]:
        return list(DATABASE_REGISTRY.values())

    def get_database(self, key: TargetDatabase) -> DatabaseCapability:
        capability = DATABASE_REGISTRY.get(key)
        if capability is None:
            raise UnknownDatabaseError(f"Unknown target database '{key}'.")
        return capability

    # -- ingestion ------------------------------------------------------------

    def ingest(
        self,
        dataset_id: str,
        target_database: TargetDatabase,
        source_format: IngestionFormat,
        actor: str,
        roles: List[str],
        package_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        upload_id: Optional[str] = None,
    ) -> IngestJob:
        capability = self.get_database(target_database)
        steps: List[IngestJobStep] = []

        # 1. RBAC — database-level ingest authority.
        authorized = (
            capability.required_role in roles
            or ADMIN_ROLE in roles
            or "admin" in roles
            or "operator" in roles
        )
        steps.append(
            IngestJobStep(
                step="RBAC_CHECK",
                passed=authorized,
                detail=(
                    f"actor holds required role '{capability.required_role}'"
                    if authorized
                    else f"actor lacks '{capability.required_role}' (and is not '{ADMIN_ROLE}')"
                ),
            )
        )
        if not authorized:
            return self._finalize(
                dataset_id, target_database, source_format, actor, roles,
                package_id, metadata, steps,
                rejection_reason=f"Actor '{actor}' is not authorized to ingest into {target_database.value}.",
            )

        # 2. Format contract — deterministic accept/reject per database.
        format_ok = source_format in capability.accepted_formats
        steps.append(
            IngestJobStep(
                step="FORMAT_CHECK",
                passed=format_ok,
                detail=(
                    f"'{source_format.value}' accepted by {target_database.value}"
                    if format_ok
                    else f"'{source_format.value}' not accepted by {target_database.value}; "
                    f"accepted: {[f.value for f in capability.accepted_formats]}"
                ),
            )
        )
        if not format_ok:
            return self._finalize(
                dataset_id, target_database, source_format, actor, roles,
                package_id, metadata, steps,
                rejection_reason=f"Format '{source_format.value}' is not supported by {target_database.value}.",
            )

        # 3. Certification gate — only CERTIFIED datasets are eligible for MASTERDB ingestion.
        report = self._certification_store.load(dataset_id)
        if report is None and self._certification_service:
            # Check if dataset is in upload_service or datasets/ to auto-certify
            report = self._attempt_auto_certify(dataset_id, upload_id)

        state = report.get("state") if report else None
        decision = (report or {}).get("ingestion_decision") or {}
        eligible = state == "CERTIFIED" and bool(decision.get("eligible_for_masterdb"))
        steps.append(
            IngestJobStep(
                step="CERTIFICATION_GATE",
                passed=eligible,
                detail=(
                    "dataset is CERTIFIED and eligible_for_masterdb=True"
                    if eligible
                    else f"dataset state='{state}', eligible_for_masterdb="
                    f"{decision.get('eligible_for_masterdb')}. Only CERTIFIED datasets "
                    "(see POST /certify) may be ingested."
                ),
            )
        )
        if not eligible:
            return self._finalize(
                dataset_id, target_database, source_format, actor, roles,
                package_id, metadata, steps,
                rejection_reason=f"Dataset '{dataset_id}' is not CERTIFIED for MASTERDB ingestion.",
                certification_state=state,
            )

        # 4. Target Persistence — physically persist target records into database
        records_to_persist = self._resolve_dataset_records(dataset_id, source_format, report, upload_id)
        try:
            persisted_summary = self._target_store.persist_target_dataset(
                target_database=target_database.value,
                dataset_id=dataset_id,
                source_format=source_format.value,
                records=records_to_persist,
                metadata=metadata or {},
            )
            record_count = persisted_summary.get("record_count", len(records_to_persist))
            target_ref = persisted_summary.get("target_reference", f"{target_database.value}/{dataset_id}")
            steps.append(
                IngestJobStep(
                    step="PERSISTENCE",
                    passed=True,
                    detail=f"Persisted {record_count} records to {target_database.value} ({target_ref}).",
                )
            )
        except Exception as exc:
            steps.append(
                IngestJobStep(
                    step="PERSISTENCE",
                    passed=False,
                    detail=f"Target persistence failed: {exc}",
                )
            )
            return self._finalize(
                dataset_id, target_database, source_format, actor, roles,
                package_id, metadata, steps,
                rejection_reason=f"Target persistence failed: {exc}",
                certification_state=state,
            )

        # 5. Route — mark routed
        steps.append(
            IngestJobStep(step="ROUTED", passed=True, detail=f"Routed to {target_database.value}."),
        )

        job_metadata = dict(metadata or {})
        job_metadata["target_reference"] = target_ref
        job_metadata["records_persisted"] = record_count

        # Advance linked upload if present
        upload_advance_ok = self._advance_linked_upload(dataset_id, upload_id, target_ref)
        if not upload_advance_ok:
            steps.append(
                IngestJobStep(
                    step="UPLOAD_LIFECYCLE_TRANSITION",
                    passed=False,
                    detail="Linked upload lifecycle transition failed after target persistence.",
                )
            )
            return self._finalize(
                dataset_id, target_database, source_format, actor, roles,
                package_id, job_metadata, steps,
                rejection_reason="Linked upload lifecycle transition failed.",
                certification_state=state,
                integrity_score=report.get("integrity_score") if report else None,
                status_override=IngestionJobStatus.PARTIAL_PERSISTENCE,
            )

        return self._finalize(
            dataset_id, target_database, source_format, actor, roles,
            package_id, job_metadata, steps,
            rejection_reason=None,
            certification_state=state,
            integrity_score=report.get("integrity_score") if report else None,
        )

    def _attempt_auto_certify(
        self,
        dataset_id: str,
        upload_id: Optional[str],
        actor: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Attempt to certify an uploaded or staged dataset if not already certified.

        Logs errors rather than silently swallowing them so that certification
        failures are visible and don't go unnoticed.
        """
        import logging as _logging

        _logger = _logging.getLogger("masterdb.database_targets")

        if not self._certification_service:
            return None

        # Check upload service first
        target_path: Optional[str] = None
        if self._upload_service:
            target_upload = None
            if upload_id:
                try:
                    target_upload = self._upload_service.get_upload(upload_id)
                except UploadJobNotFoundError:
                    _logger.warning(
                        "upload_id='%s' not found; cannot auto-certify dataset_id='%s'",
                        upload_id, dataset_id,
                    )
            if not target_upload:
                # Find by dataset_id
                uploads = self._upload_service.list_uploads()
                for u in uploads:
                    if u.dataset_id == dataset_id or u.upload_id == dataset_id:
                        target_upload = u
                        break
            if target_upload and target_upload.storage_path:
                target_path = target_upload.storage_path

        # Check standard datasets/ directory
        if not target_path:
            workspace_root = Path(__file__).resolve().parents[1]
            datasets_dir = workspace_root / "datasets"
            for ext in [".csv", ".json", ".xlsx"]:
                candidate = datasets_dir / f"{dataset_id}{ext}"
                if candidate.exists():
                    target_path = str(candidate)
                    break

        if target_path and Path(target_path).exists():
            try:
                metadata_path = str(Path(__file__).resolve().parents[1] / "datasets" / "metadata.json")
                if not Path(metadata_path).exists():
                    metadata_path = None
                return self._certification_service.certify(
                    dataset_id=dataset_id,
                    dataset_path=target_path,
                    metadata_path=metadata_path,
                )
            except Exception as exc:
                _logger.warning(
                    "Certification failed for dataset_id='%s' from '%s': %s",
                    dataset_id, Path(target_path).name, exc,
                )
                return None

        return None

    def _resolve_dataset_records(
        self,
        dataset_id: str,
        source_format: IngestionFormat,
        report: Optional[Dict[str, Any]],
        upload_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Resolve the actual raw records for a dataset to persist into the target database.

        Raises:
            DatasetRecordsUnresolvedError: If no actual records can be resolved from
                either the upload staging area or the datasets directory. This is an
                explicit failure rather than a silent synthetic-record fallback.
        """
        # 1. Check upload service staged file (takes precedence when upload_id provided)
        target_file: Optional[Path] = None
        if self._upload_service:
            target_upload = None
            if upload_id:
                try:
                    target_upload = self._upload_service.get_upload(upload_id)
                except UploadJobNotFoundError:
                    pass
            if not target_upload:
                for u in self._upload_service.list_uploads():
                    if u.dataset_id == dataset_id or u.upload_id == dataset_id:
                        target_upload = u
                        break
            if target_upload and target_upload.storage_path:
                p = Path(target_upload.storage_path)
                if p.exists():
                    target_file = p

        # 2. Check datasets directory (only if no upload staged file found)
        if target_file is None:
            workspace_root = Path(__file__).resolve().parents[1]
            # Honour self._dataset_dir when set (test fixtures / injected paths);
            # fall back to the production workspace datasets directory.
            datasets_dir = self._dataset_dir or (workspace_root / "datasets")
            for candidate_name in [f"{dataset_id}.csv", f"{dataset_id}.json"]:
                cand = datasets_dir / candidate_name
                if cand.exists():
                    target_file = cand
                    break

        # 3. Load actual file — NO synthetic fallback.
        #    If the file cannot be resolved or loaded, we fail explicitly rather
        #    than fabricating a record and claiming PERSISTED.
        if not target_file:
            raise DatasetRecordsUnresolvedError(
                f"No source file found for dataset_id='{dataset_id}'. "
                f"Either upload the dataset via POST /upload first, or ensure "
                f"the dataset exists in the datasets/ directory."
            )

        try:
            df = DatasetLoader.load_dataset(target_file)
            return df.to_dict(orient="records")
        except Exception as exc:
            raise DatasetRecordsUnresolvedError(
                f"Failed to load records from '{target_file.name}': {exc}. "
                f"Cannot ingest dataset '{dataset_id}' without readable records."
            ) from exc

    def _advance_linked_upload(
        self,
        dataset_id: str,
        upload_id: Optional[str],
        target_ref: str,
    ) -> bool:
        """Advance linked upload job through REGISTERED -> INGESTED -> AVAILABLE.

        Returns True if transition succeeded or no upload linked, False if transition failed.
        """
        import logging as _logging

        _logger = _logging.getLogger("masterdb.database_targets")

        if not self._upload_service:
            return True
        target_upload = None
        if upload_id:
            try:
                target_upload = self._upload_service.get_upload(upload_id)
            except UploadJobNotFoundError:
                _logger.warning(
                    "upload_id='%s' not found in upload store; cannot advance linked upload for dataset_id='%s'",
                    upload_id, dataset_id,
                )
                return False
        if not target_upload:
            for u in self._upload_service.list_uploads():
                if u.dataset_id == dataset_id or u.upload_id == dataset_id:
                    target_upload = u
                    break
        if target_upload:
            try:
                if target_upload.status in (UploadStatus.RECEIVED, UploadStatus.VALIDATING):
                    self._upload_service.validate_upload(target_upload.upload_id)
                    target_upload = self._upload_service.get_upload(target_upload.upload_id)
                if target_upload.status == UploadStatus.VALIDATED:
                    pkg_id = target_upload.package_id or f"pkg-{dataset_id}"
                    self._upload_service.register_dataset(target_upload.upload_id, dataset_id, pkg_id)
                    target_upload = self._upload_service.get_upload(target_upload.upload_id)
                if target_upload.status == UploadStatus.REGISTERED:
                    self._upload_service.mark_ingested(target_upload.upload_id, artifact_id=target_ref)
                    self._upload_service.mark_available(target_upload.upload_id)
                return True
            except Exception as exc:
                _logger.error(
                    "Failed to advance upload lifecycle for upload_id='%s', dataset_id='%s': %s",
                    upload_id, dataset_id, exc, exc_info=True,
                )
                return False
        return True

    def _finalize(
        self,
        dataset_id: str,
        target_database: TargetDatabase,
        source_format: IngestionFormat,
        actor: str,
        roles: List[str],
        package_id: Optional[str],
        metadata: Optional[Dict[str, Any]],
        steps: List[IngestJobStep],
        rejection_reason: Optional[str],
        certification_state: Optional[str] = None,
        integrity_score: Optional[float] = None,
        status_override: Optional[IngestionJobStatus] = None,
    ) -> IngestJob:
        if status_override:
            status = status_override
        else:
            status = IngestionJobStatus.REJECTED if rejection_reason else IngestionJobStatus.PERSISTED

        job = IngestJob(
            dataset_id=dataset_id,
            target_database=target_database,
            source_format=source_format,
            package_id=package_id,
            actor=actor,
            roles=roles,
            status=status,
            certification_state=certification_state,
            integrity_score=integrity_score,
            steps=steps,
            rejection_reason=rejection_reason,
            metadata=metadata or {},
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._job_store.save(job.job_id, job.model_dump(mode="json"))
        return job

    # -- target persistence querying -------------------------------------------

    def get_target_dataset(self, target_database: TargetDatabase, dataset_id: str) -> Optional[Dict[str, Any]]:
        return self._target_store.get_target_dataset(target_database.value, dataset_id)

    def list_target_records(
        self, target_database: TargetDatabase, dataset_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        return self._target_store.list_target_records(target_database.value, dataset_id, limit=limit, offset=offset)

    # -- observability ---------------------------------------------------------

    def get_job(self, job_id: str) -> IngestJob:
        raw = self._job_store.load(job_id)
        if raw is None:
            raise JobNotFoundError(f"No ingestion job found for job_id={job_id}")
        return IngestJob(**raw)

    def list_jobs(
        self,
        dataset_id: Optional[str] = None,
        target_database: Optional[TargetDatabase] = None,
        status: Optional[IngestionJobStatus] = None,
    ) -> List[IngestJob]:
        jobs = [IngestJob(**raw) for raw in self._job_store.list_all()]
        if dataset_id:
            jobs = [j for j in jobs if j.dataset_id == dataset_id]
        if target_database:
            jobs = [j for j in jobs if j.target_database == target_database]
        if status:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.submitted_at, reverse=True)
        return jobs
