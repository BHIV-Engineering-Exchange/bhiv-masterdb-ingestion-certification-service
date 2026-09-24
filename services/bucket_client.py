"""
Bucket Client — Evidence Preservation & Replay Storage (Phase 8).

Connects MASTERDB to Bucket for evidence preservation, provenance storage,
and artifact deposition. Designed to degrade gracefully when Bucket is
unconfigured or unreachable, consistent with every other adjacent-service
client in this codebase.

Configuration (environment variables):
    PRAVAH_BHIV_BUCKET    e.g. https://bhiv-bucket-i1l6.onrender.com
    BUCKET_API_KEY        the X-API-Key header value
"""
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("masterdb")


class BucketUnavailableError(RuntimeError):
    """Raised when Bucket is not configured or unreachable."""


class BucketClient:
    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 10.0) -> None:
        self.base_url = (base_url or os.environ.get("PRAVAH_BHIV_BUCKET") or "").rstrip("/")
        self.api_key = os.environ.get("BUCKET_API_KEY", "")
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.is_configured():
            raise BucketUnavailableError(
                "Bucket client is not configured (PRAVAH_BHIV_BUCKET missing)."
            )
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(method, url, headers=self._headers(), **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Bucket HTTP error: %s %s -> %s", method, path, exc.response.status_code)
            raise BucketUnavailableError(f"Bucket returned {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.ConnectError as exc:
            logger.warning("Bucket connection error: %s", exc)
            raise BucketUnavailableError(f"Bucket connection failed: {exc}") from exc

    # -- evidence / artifact storage ------------------------------------------

    def store_evidence(self, evidence_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Store a replayable evidence artifact in Bucket."""
        return self._request("POST", "/evidence", json={"evidence_id": evidence_id, **payload})

    def get_evidence(self, evidence_id: str) -> Dict[str, Any]:
        """Retrieve a stored evidence artifact from Bucket."""
        return self._request("GET", f"/evidence/{evidence_id}")

    def store_provenance(self, dataset_id: str, provenance: Dict[str, Any]) -> Dict[str, Any]:
        """Store a provenance record for a dataset."""
        return self._request("POST", "/provenance", json={"dataset_id": dataset_id, **provenance})

    def get_provenance(self, dataset_id: str) -> Dict[str, Any]:
        """Retrieve stored provenance for a dataset."""
        return self._request("GET", f"/provenance/{dataset_id}")

    # -- health / observability passthrough -----------------------------------

    def health(self) -> Dict[str, Any]:
        """Check Bucket health. Returns dict or raises BucketUnavailableError."""
        return self._request("GET", "/health")

    def status(self) -> Dict[str, Any]:
        return {
            "configured": self.is_configured(),
            "base_url": self.base_url or "NOT_CONFIGURED",
        }
