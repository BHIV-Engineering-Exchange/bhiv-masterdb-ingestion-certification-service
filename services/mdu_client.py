"""
MDU API client.

This is the ONLY module in MASTERDB allowed to know the MDU service's base
URL, auth header, and endpoint paths. It is a thin, honest HTTP wrapper: it
does not interpret schema semantics, does not decide compatibility, and does
not cache canonical meaning anywhere else in the codebase. Everything it
returns is treated as MDU-owned data by the caller (MDUContractAdapter).

Configuration is read from environment variables so no credentials are
hardcoded in source:
    MDU_BASE_URL           e.g. https://bhiv-mdu-api.onrender.com
    MDU_API_KEY            the X-API-Key header value
    MDU_TIMEOUT_SECONDS    client timeout (default: 30.0s for Render cold-starts)

If MDU_BASE_URL / MDU_API_KEY are not set, every method raises
MDUUnavailableError rather than silently falling back to placeholder data —
callers (MDUContractAdapter) are responsible for deciding whether a
placeholder fallback is acceptable for their use case.
"""
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from utils.trace import generate_trace_id, normalize_trace_id

logger = logging.getLogger("masterdb")


class MDUUnavailableError(RuntimeError):
    """Raised when MDU is unreachable, unconfigured, or returns an error."""


class MDUClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("MDU_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("MDU_API_KEY")
        if timeout_seconds is not None:
            self.timeout_seconds = timeout_seconds
        else:
            self.timeout_seconds = float(os.environ.get("MDU_TIMEOUT_SECONDS", "30.0"))

        # Circuit breaker to prevent cascading failures if MDU is down.
        from middleware.circuit_breaker import CircuitBreaker

        self._circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.environ.get("MDU_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
            timeout_seconds=float(os.environ.get("MDU_CIRCUIT_BREAKER_TIMEOUT_SECONDS", "60")),
        )

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _sanitize(self, message: str) -> str:
        """Strip raw API key from strings to guarantee zero secret leakage."""
        if self.api_key and self.api_key in message:
            return message.replace(self.api_key, "[REDACTED]")
        return message

    def _build_headers(self, trace_id: Optional[str] = None) -> Dict[str, str]:
        tid = normalize_trace_id(trace_id) if trace_id else generate_trace_id()
        return {
            "X-API-Key": self.api_key or "",
            "X-Trace-Id": tid,
        }

    # -- Read contract surface -----------------------------------------------

    def get_dataset_schema(self, dataset_id: str, trace_id: Optional[str] = None) -> Any:
        return self._get(f"/api/v1/schemas/dataset/{dataset_id}", trace_id=trace_id)

    def get_dataset_provenance(self, dataset_id: str, trace_id: Optional[str] = None) -> Any:
        return self._get(f"/api/v1/datasets/{dataset_id}/provenance", trace_id=trace_id)

    def get_canonical_dataset(self, dataset_id: str, trace_id: Optional[str] = None) -> Any:
        return self._get(f"/api/v1/datasets/canonical/{dataset_id}", trace_id=trace_id)

    def validate_all_provenance(self, trace_id: Optional[str] = None) -> Any:
        return self._get("/api/v1/discovery/provenance/validate-all", trace_id=trace_id)

    def get_discovery_summary(self, trace_id: Optional[str] = None) -> Any:
        return self._get("/api/v1/discovery/summary", trace_id=trace_id)

    def get_dataset_relationships(self, dataset_id: str, trace_id: Optional[str] = None) -> Any:
        return self._get(f"/api/v1/relationships/dataset/{dataset_id}", trace_id=trace_id)

    # -- Write contract surface ----------------------------------------------

    def record_provenance(
        self, dataset_id: str, payload: Dict[str, Any], trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Record a provenance event against MDU via POST /api/v1/datasets/{dataset_id}/provenance.
        `dataset_id` MUST be MDU's internal UUID.
        """
        return self._post(f"/api/v1/datasets/{dataset_id}/provenance", json_data=payload, trace_id=trace_id)

    def create_relationship(
        self, payload: Dict[str, Any], trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a lineage relationship edge between datasets via POST /api/v1/relationships/.
        `parent_dataset_id` and `child_dataset_id` in payload MUST be MDU UUIDs.
        """
        return self._post("/api/v1/relationships/", json_data=payload, trace_id=trace_id)

    # -- internal HTTP handlers ----------------------------------------------

    def _get(self, path: str, trace_id: Optional[str] = None) -> Any:
        if not self.is_configured():
            raise MDUUnavailableError(
                "MDU client is not configured (MDU_BASE_URL / MDU_API_KEY missing). "
                "Set both environment variables to enable live MDU integration."
            )
        url = f"{self.base_url}{path}"
        headers = self._build_headers(trace_id)
        try:
            response = self._circuit_breaker.call(
                httpx.get,
                url,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            logger.info("MDU request ok path=%s status=%s", path, response.status_code)
            return response.json()
        except httpx.HTTPStatusError as exc:
            safe_err = self._sanitize(str(exc))
            if exc.response.status_code == 401:
                logger.warning("MDU auth failed path=%s status=401", path)
                raise MDUUnavailableError(
                    f"MDU authentication failed (HTTP 401 Unauthorized) for {path}. "
                    "Verify MDU_API_KEY is correctly provisioned."
                ) from exc
            if exc.response.status_code == 403:
                logger.warning("MDU forbidden path=%s status=403", path)
                raise MDUUnavailableError(
                    f"MDU access forbidden (HTTP 403 Forbidden) for {path}."
                ) from exc
            logger.warning("MDU HTTP error path=%s status=%s", path, exc.response.status_code)
            raise MDUUnavailableError(f"MDU request failed for {path} with status {exc.response.status_code}: {safe_err}") from exc
        except Exception as exc:
            if isinstance(exc, MDUUnavailableError):
                raise
            safe_err = self._sanitize(str(exc))
            logger.warning("MDU request failed path=%s error=%s", path, safe_err)
            raise MDUUnavailableError(f"MDU request failed for {path}: {safe_err}") from exc

    def _post(self, path: str, json_data: Dict[str, Any], trace_id: Optional[str] = None) -> Any:
        if not self.is_configured():
            raise MDUUnavailableError(
                "MDU client is not configured (MDU_BASE_URL / MDU_API_KEY missing). "
                "Set both environment variables to enable live MDU integration."
            )
        url = f"{self.base_url}{path}"
        headers = self._build_headers(trace_id)
        headers["Content-Type"] = "application/json"
        try:
            response = self._circuit_breaker.call(
                httpx.post,
                url,
                json=json_data,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            logger.info("MDU post ok path=%s status=%s", path, response.status_code)
            return response.json()
        except httpx.HTTPStatusError as exc:
            safe_err = self._sanitize(str(exc))
            if exc.response.status_code == 401:
                logger.warning("MDU auth failed path=%s status=401", path)
                raise MDUUnavailableError(
                    f"MDU authentication failed (HTTP 401 Unauthorized) for {path}. "
                    "Verify MDU_API_KEY is correctly provisioned."
                ) from exc
            if exc.response.status_code == 403:
                logger.warning("MDU forbidden path=%s status=403", path)
                raise MDUUnavailableError(
                    f"MDU access forbidden (HTTP 403 Forbidden) for {path}."
                ) from exc
            logger.warning("MDU HTTP error path=%s status=%s", path, exc.response.status_code)
            raise MDUUnavailableError(f"MDU request failed for {path} with status {exc.response.status_code}: {safe_err}") from exc
        except Exception as exc:
            if isinstance(exc, MDUUnavailableError):
                raise
            safe_err = self._sanitize(str(exc))
            logger.warning("MDU post failed path=%s error=%s", path, safe_err)
            raise MDUUnavailableError(f"MDU post failed for {path}: {safe_err}") from exc
