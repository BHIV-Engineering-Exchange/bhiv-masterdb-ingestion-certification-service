"""
Upload Service — Canonical MASTERDB File Upload & Ingestion Logic.

This service implements the governed upload capability for MASTERDB.
"""
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from upload.models import UploadJob, UploadJobStep, UploadStatus
from upload.store import UploadJobNotFoundError, UploadStore

logger = logging.getLogger("masterdb")

ALLOWED_CONTENT_TYPES = {
    "text/csv", "application/json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/pdf", "text/plain", "image/png", "image/jpeg",
    "image/gif", "application/zip",
}

MAX_FILE_SIZE_BYTES = int(os.environ.get("MASTERDB_UPLOAD_MAX_SIZE_BYTES", 500 * 1024 * 1024))


class UploadValidationError(Exception):
    """Raised when upload validation fails."""


class UploadStateError(Exception):
    """Raised when upload state transition is invalid."""


class UploadService:
    """Service for managing upload jobs in MASTERDB."""

    def __init__(self, store: Optional[UploadStore] = None, staging_dir: str = "upload_staging") -> None:
        self._store = store or UploadStore()
        self._staging_dir = Path(staging_dir)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        filename = os.path.basename(filename)
        filename = re.sub(r"[^\w\-.,]", "_", filename)
        return filename[:255]

    def _validate_content_type(self, content_type: str) -> None:
        if content_type.lower() not in ALLOWED_CONTENT_TYPES:
            raise UploadValidationError(
                f"Content type '{content_type}' not allowed. "
                f"Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
            )

    def _validate_file_size(self, file_size: int) -> None:
        if file_size > MAX_FILE_SIZE_BYTES:
            raise UploadValidationError(
                f"File size {file_size} exceeds max {MAX_FILE_SIZE_BYTES}"
            )
        if file_size < 1:
            raise UploadValidationError("File size must be at least 1 byte")

    def _validate_filename(self, filename: str) -> None:
        if not filename or len(filename.strip()) == 0:
            raise UploadValidationError("Filename cannot be empty")
        if len(filename) > 255:
            raise UploadValidationError("Filename exceeds 255 characters")
        if ".." in filename or "/" in filename or "\\" in filename:
            raise UploadValidationError("Invalid path characters in filename")

    def _compute_checksum(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def initiate_upload(
        self,
        filename: str,
        content_type: str,
        file_size: int,
        actor: str,
        roles: List[str],
        checksum_sha256: Optional[str] = None,
        classification: Optional[str] = None,
        source_reference: Optional[str] = None,
        provenance_metadata: Optional[Dict[str, Any]] = None,
        schema_version: Optional[str] = None,
        product_source: Optional[str] = None,
        intended_use: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UploadJob:
        self._validate_filename(filename)
        self._validate_content_type(content_type)
        self._validate_file_size(file_size)
        job = UploadJob(
            filename=filename, content_type=content_type, file_size=file_size,
            checksum_sha256=checksum_sha256, classification=classification,
            source_reference=source_reference, provenance_metadata=provenance_metadata or {},
            schema_version=schema_version, product_source=product_source,
            intended_use=intended_use, actor=actor, roles=roles,
            status=UploadStatus.UPLOADED, metadata=metadata or {},
        )
        staging_path = self._get_staging_path(job.upload_id, filename)
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        job.storage_path = str(staging_path)
        job.steps.append(UploadJobStep(step="UPLOAD_INITIATED", passed=True, detail=f"Upload session created for {filename}"))
        self._store.save(job)
        return job

    def _get_staging_path(self, upload_id: str, filename: str) -> Path:
        safe_filename = self._sanitize_filename(filename)
        return self._staging_dir / upload_id / safe_filename

    def receive_upload(self, upload_id: str, file_content: bytes) -> UploadJob:
        job = self._store.load(upload_id)
        if job is None:
            raise UploadJobNotFoundError(f"Upload job {upload_id} not found")
        if job.status != UploadStatus.UPLOADED:
            raise UploadStateError(f"Cannot receive upload in state {job.status}")
        if len(file_content) != job.file_size:
            job.status = UploadStatus.REJECTED
            job.rejection_reason = f"Size mismatch: expected {job.file_size}, got {len(file_content)}"
            job.steps.append(UploadJobStep(step="RECEIVE_VALIDATION", passed=False, detail=job.rejection_reason))
            self._store.save(job)
            raise UploadValidationError(job.rejection_reason)
        staging_path = Path(job.storage_path)
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        with staging_path.open("wb") as f:
            f.write(file_content)
        job.status = UploadStatus.RECEIVED
        job.received_at = job.steps[-1].at
        job.steps.append(UploadJobStep(step="RECEIVED", passed=True, detail=f"File staged at {job.storage_path}"))
        self._store.save(job)
        return job

    def validate_upload(self, upload_id: str) -> UploadJob:
        job = self._store.load(upload_id)
        if job is None:
            raise UploadJobNotFoundError(f"Upload job {upload_id} not found")
        if job.status != UploadStatus.RECEIVED:
            raise UploadStateError(f"Cannot validate upload in state {job.status}")
        job.status = UploadStatus.VALIDATING
        job.steps.append(UploadJobStep(step="VALIDATING", passed=True, detail="Starting validation"))
        errors: List[str] = []
        staging_path = Path(job.storage_path)
        if not staging_path.exists():
            errors.append(f"Staged file not found at {job.storage_path}")
        checksum_verified = False
        if staging_path.exists():
            actual_size = staging_path.stat().st_size
            if actual_size != job.file_size:
                errors.append(f"File size mismatch: expected {job.file_size}, actual {actual_size}")
            if job.checksum_sha256:
                try:
                    computed = self._compute_checksum(staging_path)
                    if computed.lower() == job.checksum_sha256.lower():
                        checksum_verified = True
                    else:
                        errors.append(f"Checksum mismatch: expected {job.checksum_sha256}, computed {computed}")
                except Exception as exc:
                    errors.append(f"Checksum computation failed: {exc}")
        job.steps.append(UploadJobStep(step="VALIDATION", passed=len(errors) == 0, detail=f"Validation completed. Errors: {len(errors)}"))
        if errors:
            job.status = UploadStatus.REJECTED
            job.rejection_reason = "; ".join(errors)
        else:
            job.status = UploadStatus.VALIDATED
            job.validated_at = job.steps[-1].at
        self._store.save(job)
        return job

    def get_upload(self, upload_id: str) -> UploadJob:
        job = self._store.load(upload_id)
        if job is None:
            raise UploadJobNotFoundError(f"Upload job {upload_id} not found")
        return job

    def list_uploads(self, status: Optional[UploadStatus] = None, actor: Optional[str] = None,
                     product_source: Optional[str] = None) -> List[UploadJob]:
        return self._store.list_all(status=status, actor=actor, product_source=product_source)

    def cancel_upload(self, upload_id: str, reason: str) -> UploadJob:
        job = self._store.load(upload_id)
        if job is None:
            raise UploadJobNotFoundError(f"Upload job {upload_id} not found")
        if job.status in (UploadStatus.AVAILABLE, UploadStatus.REJECTED):
            raise UploadStateError(f"Cannot cancel upload in terminal state {job.status}")
        if job.storage_path:
            staging_path = Path(job.storage_path)
            if staging_path.exists():
                if staging_path.is_file():
                    staging_path.unlink()
                if staging_path.parent.exists():
                    try:
                        staging_path.parent.rmdir()
                    except OSError:
                        pass
        job.status = UploadStatus.REJECTED
        job.rejection_reason = f"Cancelled: {reason}"
        job.steps.append(UploadJobStep(step="CANCELLED", passed=True, detail=f"Upload cancelled by {job.actor}: {reason}"))
        self._store.save(job)
        return job

    def link_ingestion_job(self, upload_id: str, ingestion_job_id: str) -> UploadJob:
        job = self.get_upload(upload_id)
        if job.status != UploadStatus.VALIDATED:
            raise UploadStateError(f"Cannot link ingestion job in state {job.status}")
        job.ingestion_job_id = ingestion_job_id
        job.steps.append(UploadJobStep(step="INGESTION_JOB_LINKED", passed=True, detail=f"Linked to ingestion job {ingestion_job_id}"))
        return self._store.save(job)

    def register_dataset(self, upload_id: str, dataset_id: str, package_id: str) -> UploadJob:
        job = self.get_upload(upload_id)
        if job.status != UploadStatus.VALIDATED:
            raise UploadStateError(f"Cannot register dataset in state {job.status}")
        job.dataset_id = dataset_id
        job.package_id = package_id
        job.status = UploadStatus.REGISTERED
        job.registered_at = job.steps[-1].at
        job.steps.append(UploadJobStep(step="REGISTERED", passed=True, detail=f"Registered as dataset {dataset_id}"))
        return self._store.save(job)

    def mark_ingested(self, upload_id: str, artifact_id: str) -> UploadJob:
        job = self.get_upload(upload_id)
        if job.status != UploadStatus.REGISTERED:
            raise UploadStateError(f"Cannot mark ingested in state {job.status}")
        job.artifact_id = artifact_id
        job.status = UploadStatus.INGESTED
        job.ingested_at = job.steps[-1].at
        job.steps.append(UploadJobStep(step="INGESTED", passed=True, detail=f"Artifact {artifact_id} created"))
        return self._store.save(job)

    def mark_available(self, upload_id: str) -> UploadJob:
        job = self.get_upload(upload_id)
        if job.status != UploadStatus.INGESTED:
            raise UploadStateError(f"Cannot mark available in state {job.status}")
        job.status = UploadStatus.AVAILABLE
        job.available_at = job.steps[-1].at
        job.steps.append(UploadJobStep(step="AVAILABLE", passed=True, detail="Dataset is now queryable and discoverable"))
        return self._store.save(job)