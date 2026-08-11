"""
InsightBridge API client.

InsightBridge (Vijay Dhawan's InsightFlow/InsightBridge/InsightCore
territory) is, as of 6 Aug 2026, the ONE adjacent service in this task's
entire history that's been confirmed actually live and reachable — see
CONSTITUTIONAL_RUNTIME_DEFINITION.md §4. Its root page self-describes as
"InsightBridge API Gateway v4.2" and names /health, /ingest, /docs,
/openapi.json as its endpoints.

WHAT'S CONFIRMED vs. ASSUMED:
- CONFIRMED: /health and /ingest exist as paths (from the gateway's own
  root-page self-description, fetched live).
- ASSUMED, NOT CONFIRMED: the exact request/response shape of POST
  /ingest. The full OpenAPI spec at /openapi.json could not be fetched
  from this environment (tool access restricted to URLs already surfaced
  in conversation/search — /openapi.json wasn't one). The payload shape
  below is a reasonable guess (service name, metric type, structured
  data, timestamp) — NOT a confirmed contract. Treat any successful
  /ingest call as "the endpoint accepted something," not "the endpoint
  is being used correctly," until someone with real access to
  /openapi.json (or Vijay Dhawan directly) confirms the real schema.

Mirrors services/mdu_client.py's pattern: thin wrapper, env-var
configured, raises rather than silently falling back, only module that
knows InsightBridge's base URL/paths.

Configuration:
    PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE   e.g. https://insightbridge-...onrender.com
    (matches the actual env var name from the ecosystem's own config,
    shared 6 Aug 2026 — using their name rather than inventing a new one
    so this plugs in directly once that variable is actually set here.)
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("masterdb")


class InsightBridgeUnavailableError(RuntimeError):
    """Raised when InsightBridge is unreachable, unconfigured, or returns an error."""


class InsightBridgeClient:
    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 10.0) -> None:
        self.base_url = (base_url or os.environ.get("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE") or "").rstrip("/")
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def health_check(self) -> Dict[str, Any]:
        return self._get("/health")

    def ingest(self, source: str, metric_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Payload shape is an assumption — see module docstring. `source`
        is meant to identify MASTERDB as the sender so InsightBridge can
        attribute the data; `metric_type` and `data` are a guess at a
        reasonable minimal envelope, not a confirmed field contract."""
        payload = {
            "source": source,
            "metric_type": metric_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return self._post("/ingest", payload)

    # -- internal -------------------------------------------------------------

    def _get(self, path: str) -> Dict[str, Any]:
        if not self.is_configured():
            raise InsightBridgeUnavailableError(
                "InsightBridge client is not configured (PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE "
                "missing). Set that environment variable to enable live InsightBridge calls."
            )
        url = f"{self.base_url}{path}"
        try:
            response = httpx.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            logger.info("InsightBridge request ok path=%s status=%s", path, response.status_code)
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("InsightBridge request failed path=%s status=%s", path, exc.response.status_code)
            raise InsightBridgeUnavailableError(
                f"InsightBridge returned {exc.response.status_code} for {path}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("InsightBridge request error path=%s error=%s", path, exc)
            raise InsightBridgeUnavailableError(f"InsightBridge request failed for {path}: {exc}") from exc

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_configured():
            raise InsightBridgeUnavailableError(
                "InsightBridge client is not configured (PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE "
                "missing). Set that environment variable to enable live InsightBridge calls."
            )
        url = f"{self.base_url}{path}"
        try:
            response = httpx.post(url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            logger.info("InsightBridge request ok path=%s status=%s", path, response.status_code)
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("InsightBridge request failed path=%s status=%s", path, exc.response.status_code)
            raise InsightBridgeUnavailableError(
                f"InsightBridge returned {exc.response.status_code} for {path}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("InsightBridge request error path=%s error=%s", path, exc)
            raise InsightBridgeUnavailableError(f"InsightBridge request failed for {path}: {exc}") from exc
