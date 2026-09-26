"""
Upload Store — Persistence layer for upload jobs.

Uses the same ArtifactStore pattern as other MASTERDB stores,
persisting upload job records as JSON files in a dedicated directory.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from upload.models import UploadJob, UploadStatus

logger = logging.getLogger("masterdb")


class UploadJobNotFoundError(KeyError):
    """Raised when upload_id does not exist in the upload job store."""


class UploadStore:
    """
    Persists upload job records to disk.

    Uses the same ArtifactStore pattern as other MASTERDB stores,
    allowing for future migration to SqlArtifactStore if needed.
    """

    def __init__(self, store_dir: str = "upload_store") -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _upload_path(self, upload_id: str) -> Path:
        """Get the file path for an upload job."""
        return self.store_dir / f"{upload_id}.json"

    def save(self, upload_job: UploadJob) -> UploadJob:
        """Save an upload job to the store."""
        path = self._upload_path(upload_job.upload_id)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(upload_job.model_dump(mode="json"), handle, indent=4)
        return upload_job

    def load(self, upload_id: str) -> Optional[UploadJob]:
        """Load an upload job from the store."""
        path = self._upload_path(upload_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return UploadJob(**data)

    def delete(self, upload_id: str) -> bool:
        """Delete an upload job from the store."""
        path = self._upload_path(upload_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(
        self,
        status: Optional[UploadStatus] = None,
        actor: Optional[str] = None,
        product_source: Optional[str] = None,
    ) -> List[UploadJob]:
        """
        List all upload jobs, optionally filtered.

        Deterministic ordering: results are sorted by upload_id
        so repeated calls always return the same order.
        """
        jobs: List[UploadJob] = []
        for path in sorted(self.store_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                job = UploadJob(**json.load(handle))
                if status is not None and job.status != status:
                    continue
                if actor is not None and job.actor != actor:
                    continue
                if product_source is not None and job.product_source != product_source:
                    continue
                jobs.append(job)
        return jobs

    def exists(self, upload_id: str) -> bool:
        """Check if an upload job exists."""
        return self._upload_path(upload_id).exists()

    def count(self, status: Optional[UploadStatus] = None) -> int:
        """Count upload jobs, optionally filtered by status."""
        return len(self.list_all(status=status))
