"""
MDU API client.

This is the ONLY module in MASTERDB allowed to know the MDU service's base
URL, auth header, and endpoint paths. It is a thin, honest HTTP wrapper: it
does not interpret schema semantics, does not decide compatibility, and does
not cache canonical meaning anywhere else in the codebase. Everything it
returns is treated as MDU-owned data by the caller (MDUContractAdapter).

Configuration is read from environment variables so no credentials are
hardcoded in source:
    MDU_BASE_URL   e.g. https://bhiv-mdu-api.onrender.com
    MDU_API_KEY    the X-API-Key header value

If MDU_BASE_URL / MDU_API_KEY are not set, every method raises
MDUUnavailableError rather than silently falling back to placeholder data —
callers (MDUContractAdapter) are responsible for deciding whether a
placeholder fallback is acceptable for their use case.
"""
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("masterdb")


class MDUUnavailableError(RuntimeError):
    """Raised when MDU is unreachable, unconfigured, or returns an error."""


class MDUClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("MDU_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("MDU_API_KEY")
        self.timeout_seconds = timeout_seconds

        # Circuit breaker to prevent cascading failures if MDU is down.
        from middleware.circuit_breaker import CircuitBreaker

        self._circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.environ.get("MDU_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
            timeout_seconds=float(os.environ.get("MDU_CIRCUIT_BREAKER_TIMEOUT_SECONDS", "60")),
        )

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    # -- Phase 1 contract surface --------------------------------------------

    def get_dataset_schema(self, dataset_id: str) -> Dict[str, Any]:
        return self._get(f"/api/v1/schemas/dataset/{dataset_id}")

    def get_dataset_provenance(self, dataset_id: str) -> Dict[str, Any]:
        return self._get(f"/api/v1/datasets/{dataset_id}/provenance")

    def get_canonical_dataset(self, dataset_id: str) -> Dict[str, Any]:
        return self._get(f"/api/v1/datasets/canonical/{dataset_id}")

    def validate_all_provenance(self) -> Dict[str, Any]:
        return self._get("/api/v1/discovery/provenance/validate-all")

    def get_discovery_summary(self) -> Dict[str, Any]:
        return self._get("/api/v1/discovery/summary")

    # -- internal -------------------------------------------------------------

    def _get(self, path: str) -> Dict[str, Any]:
        if not self.is_configured():
            raise MDUUnavailableError(
                "MDU client is not configured (MDU_BASE_URL / MDU_API_KEY missing). "
                "Set both environment variables to enable live MDU integration."
            )
        url = f"{self.base_url}{path}"
        try:
            response = self._circuit_breaker.call(
                httpx.get,
                url,
                headers={"X-API-Key": self.api_key},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            logger.info("MDU request ok path=%s status=%s", path, response.status_code)
            return response.json()
        except Exception as exc:
            logger.warning("MDU request failed path=%s error=%s", path, exc)
            if isinstance(exc, MDUUnavailableError):
                raise
            raise MDUUnavailableError(f"MDU request failed for {path}: {exc}") from exc
