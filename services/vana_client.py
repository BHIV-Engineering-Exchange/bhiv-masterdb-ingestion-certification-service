"""
VANA API Client — Forest, Mangrove, Carbon & Spatial Governance Integration.

This module provides the integration client for VANA's governed data surfaces:
1. 6-Tuple Governance Evaluation Gate (POST /api/v1/governance/evaluate)
2. Governed Datasets Catalog (GET /api/v1/governance/datasets)
3. Canonical Observations & Provenance Joins (GET /api/v1/observations/real, GET /api/v1/official/forest-cover/records)
4. Spatial GIS GeoJSON Layers (GET /api/v1/spatial/layers, GET /api/v1/spatial/geojson/{layer_id}, GET /api/v1/spatial/envelope)
5. Carbon Quantification Engine (GET /api/v1/carbon/summary, GET /api/v1/carbon/maharashtra, GET /api/v1/carbon/thane-creek)
6. Constitutional Execution Gate - TANTRA Runtime (POST /vana/execute)

Configuration:
    VANA_BASE_URL: Base URL of the VANA service (e.g. http://localhost:8001 or http://localhost:8000)
    VANA_API_KEY: Service-to-service API key for X-API-Key header
"""
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("masterdb")

DEFAULT_VANA_API_KEY = "2b899caf7e3aea924c96761326bdded5162da31a9d1fdba59a2a451d2335c778"


class VanaUnavailableError(RuntimeError):
    """Raised when VANA is unreachable, unconfigured, or returns an error."""


class VanaGovernanceDeniedError(PermissionError):
    """Raised when VANA 6-tuple governance evaluation decision is DENIED."""


class VanaClient:
    """Client for VANA Forest, Mangrove & Carbon Governance API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("VANA_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("VANA_API_KEY") or DEFAULT_VANA_API_KEY
        self.timeout_seconds = timeout_seconds

        # Circuit breaker to prevent cascading failures if VANA is down.
        from middleware.circuit_breaker import CircuitBreaker

        self._circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.environ.get("VANA_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")),
            timeout_seconds=float(os.environ.get("VANA_CIRCUIT_BREAKER_TIMEOUT_SECONDS", "60")),
        )

    def is_configured(self) -> bool:
        """Returns True if base_url is configured."""
        return bool(self.base_url)

    # -------------------------------------------------------------------------
    # 1. 6-Tuple Governance Evaluation Gate
    # -------------------------------------------------------------------------

    def evaluate_governance(
        self,
        actor: str = "MASTERDB",
        role: str = "APPROVED_CONSUMER",
        dataset_id: str = "DS-FSI-ISFR-2023-FOREST-COVER",
        action: str = "READ",
        purpose: str = "DISTRICT_CANOPY_ANALYSIS",
        environment: str = "production",
    ) -> Dict[str, Any]:
        """
        Evaluate 6-tuple governance gate via POST /api/v1/governance/evaluate.
        Returns decision (ALLOWED, CONTROLLED, REQUIRES_APPROVAL, DENIED) with rule codes and audit trail.
        """
        payload = {
            "actor": actor,
            "role": role,
            "dataset_id": dataset_id,
            "action": action,
            "purpose": purpose,
            "environment": environment,
        }
        res = self._post("/api/v1/governance/evaluate", payload)
        decision = (res.get("decision") or res.get("status") or "").upper()
        if decision == "DENIED":
            reason = res.get("reason") or res.get("detail") or "Access denied by VANA 6-tuple governance policy."
            raise VanaGovernanceDeniedError(reason)
        return res

    # -------------------------------------------------------------------------
    # 2. Governed Datasets Catalog
    # -------------------------------------------------------------------------

    def get_governed_datasets(self) -> Dict[str, Any]:
        """Retrieve complete inventory of governed datasets with classifications and custodians."""
        return self._get("/api/v1/governance/datasets")

    # -------------------------------------------------------------------------
    # 3. Canonical Observations & Provenance Joins
    # -------------------------------------------------------------------------

    def get_real_observations(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Retrieve ground truth observations joined with metrics and immutable source provenance."""
        return self._get("/api/v1/observations/real", params=params)

    def get_forest_cover_records(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Retrieve FSI ISFR 2023 official district canopy & mangrove records."""
        return self._get("/api/v1/official/forest-cover/records", params=params)

    # -------------------------------------------------------------------------
    # 4. Spatial GIS GeoJSON Layers
    # -------------------------------------------------------------------------

    def get_spatial_layers(self) -> Dict[str, Any]:
        """Retrieve spatial layer index (Sanctuary boundary, mangrove density, nurseries)."""
        return self._get("/api/v1/spatial/layers")

    def get_spatial_geojson(self, layer_id: str) -> Dict[str, Any]:
        """Retrieve RFC 7946 WGS84 GeoJSON features for layer_id."""
        return self._get(f"/api/v1/spatial/geojson/{layer_id}")

    def get_spatial_envelope(self) -> Dict[str, Any]:
        """Retrieve unified spatial bounding box."""
        return self._get("/api/v1/spatial/envelope")

    # -------------------------------------------------------------------------
    # 5. Carbon Quantification Engine
    # -------------------------------------------------------------------------

    def get_carbon_summary(self) -> Dict[str, Any]:
        """Retrieve combined forest carbon + Thane Creek Blue Carbon summary."""
        return self._get("/api/v1/carbon/summary")

    def get_carbon_maharashtra(self) -> Dict[str, Any]:
        """Retrieve forest carbon stock (215.34 MtC)."""
        return self._get("/api/v1/carbon/maharashtra")

    def get_carbon_thane_creek(self) -> Dict[str, Any]:
        """Retrieve mangrove blue carbon with measured vs satellite segregation."""
        return self._get("/api/v1/carbon/thane-creek")

    # -------------------------------------------------------------------------
    # 6. Constitutional Execution Gate (TANTRA Runtime)
    # -------------------------------------------------------------------------

    def execute_constitutional_runtime(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Enforces Authority, Doctrine, Semantic, and Lineage gates via POST /vana/execute."""
        return self._post("/vana/execute", payload)

    # -------------------------------------------------------------------------
    # HTTP Transport Helpers
    # -------------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.is_configured():
            raise VanaUnavailableError("VANA_BASE_URL is not configured; cannot call VANA API.")

        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                res = self._circuit_breaker.call(
                    client.get,
                    url,
                    headers=self._headers(),
                    params=params,
                )
                res.raise_for_status()
                return res.json()
        except Exception as exc:
            logger.warning("VANA GET %s failed: %s", path, exc)
            raise VanaUnavailableError(f"VANA call to {path} failed: {exc}") from exc

    def _post(self, path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_configured():
            raise VanaUnavailableError("VANA_BASE_URL is not configured; cannot call VANA API.")

        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                res = self._circuit_breaker.call(
                    client.post,
                    url,
                    headers=self._headers(),
                    json=json_body,
                )
                res.raise_for_status()
                return res.json()
        except Exception as exc:
            logger.warning("VANA POST %s failed: %s", path, exc)
            raise VanaUnavailableError(f"VANA call to {path} failed: {exc}") from exc
