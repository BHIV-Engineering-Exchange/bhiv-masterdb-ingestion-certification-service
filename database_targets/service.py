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
     database (no direct UI-to-database bypass, no blind ingestion)
  4. record a fully auditable ingestion job: actor, dataset, source
     format, target, timestamp, validation/certification result, and
     outcome — including rejected attempts, which stay traceable too.

Every check (RBAC, format, certification gate) is recorded as an
`IngestJobStep` regardless of outcome, and every job — accepted or
rejected — is persisted, so `GET /ingest/jobs/{job_id}` always has the
full reasoning trail for the dashboard's validation-feedback / result
states.
"""
from datetime import datetime, timezone
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
from services.artifact_store import ArtifactStore


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
    ) -> None:
        # Reads certification decisions from the *same* artifact store the
        # existing certification pipeline already writes to (main.py wires
        # this to the shared `artifact_store` instance) — this is the
        # "attach, don't rebuild" boundary: this service never re-runs
        # validation, it only reads the decision that's already there.
        self._certification_store = certification_artifact_store
        self._job_store = ArtifactStore(reports_dir=store_dir)

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
    ) -> IngestJob:
        capability = self.get_database(target_database)
        steps: List[IngestJobStep] = []

        # 1. RBAC — database-level ingest authority. Visibility of a
        # database (GET /databases) never implies write authority here.
        authorized = capability.required_role in roles or ADMIN_ROLE in roles
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

        # 3. Certification gate — only CERTIFIED datasets are eligible for
        # MASTERDB ingestion (see README.md "Certification States"). This
        # reads the decision the existing CertificationService already
        # produced; it does not recompute it.
        report = self._certification_store.load(dataset_id)
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

        # 4. Route — the routing decision itself is what this service
        # guarantees is durable and auditable. The physical write into
        # each database's own storage engine is that database's concern,
        # out of scope for this convergence task (see task PDF section 1).
        steps.append(
            IngestJobStep(step="ROUTED", passed=True, detail=f"Routed to {target_database.value}."),
        )
        return self._finalize(
            dataset_id, target_database, source_format, actor, roles,
            package_id, metadata, steps,
            rejection_reason=None,
            certification_state=state,
            integrity_score=report.get("integrity_score") if report else None,
        )

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
    ) -> IngestJob:
        job = IngestJob(
            dataset_id=dataset_id,
            target_database=target_database,
            source_format=source_format,
            package_id=package_id,
            actor=actor,
            roles=roles,
            status=IngestionJobStatus.REJECTED if rejection_reason else IngestionJobStatus.PERSISTED,
            certification_state=certification_state,
            integrity_score=integrity_score,
            steps=steps,
            rejection_reason=rejection_reason,
            metadata=metadata or {},
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._job_store.save(job.job_id, job.model_dump(mode="json"))
        return job

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
