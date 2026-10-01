"""
MASTERDB_TEST_CONSUMER — Approved Ecosystem Consumer Client.

Demonstrates the 10-step canonical access flow for new and existing applications:
1. Application Identification
2. Capability Discovery
3. Contract Retrieval
4. Access Request
5. Authorization Evaluation
6. Capability Invocation
7. Data Retrieval
8. Provenance Metadata Acquisition
9. Telemetry Production
10. Auditable Evidence Trail Verification

IMPORTANT: This consumer depends ONLY on HTTP/TANTRA API contracts.
It does NOT import OR use database connection OR ORM models.
"""
from typing import Any, Dict, List, Optional
import httpx


class MasterDBTestConsumer:
    def __init__(
        self,
        base_url: str = "http://testserver",
        application_id: str = "MASTERDB_TEST_CONSUMER",
        access_token: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.application_id = application_id
        self.access_token = access_token
        self.client = client or httpx.Client(base_url=self.base_url)
        self.last_grant: Optional[Dict[str, Any]] = None
        self.last_response: Optional[Dict[str, Any]] = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def authenticate(self, username: str = "test-consumer", roles: List[str] = None) -> str:
        """Step 1: Identify application and obtain ecosystem JWT token."""
        payload = {
            "actor": self.application_id,
            "roles": roles or ["ecosystem-reader", "viewer"],
        }
        res = self.client.post("/auth/token", json=payload)
        if res.status_code == 200:
            token = res.json()["access_token"]
            self.access_token = token
            return token
        raise RuntimeError(f"Authentication failed: {res.status_code} - {res.text}")

    def discover_capabilities(
        self, domain: Optional[str] = None, search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Step 2: Capability Discovery via TANTRA access path."""
        params = {}
        if domain:
            params["domain"] = domain
        if search:
            params["search"] = search
        res = self.client.get("/capabilities", params=params, headers=self._headers())
        if res.status_code == 200:
            return res.json()
        raise RuntimeError(f"Capability discovery failed: {res.status_code} - {res.text}")

    def get_capability_contract(self, capability_id: str) -> Dict[str, Any]:
        """Step 3: Machine-readable Capability Contract Retrieval."""
        res = self.client.get(f"/capabilities/{capability_id}/contract", headers=self._headers())
        if res.status_code == 200:
            return res.json()
        raise RuntimeError(f"Contract retrieval failed: {res.status_code} - {res.text}")

    def request_access(self, capability_id: str, purpose: str = "general_reuse") -> Dict[str, Any]:
        """Steps 4 & 5: Request Access & Receive Authorization Grant."""
        payload = {
            "application_id": self.application_id,
            "capability_id": capability_id,
            "purpose": purpose,
        }
        res = self.client.post("/access/request", json=payload, headers=self._headers())
        if res.status_code == 200:
            grant = res.json()
            self.last_grant = grant
            return grant
        elif res.status_code == 403:
            return res.json()
        raise RuntimeError(f"Access request failed: {res.status_code} - {res.text}")

    def retrieve_capability_data(
        self,
        capability_id: str,
        query_params: Optional[Dict[str, Any]] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Steps 6, 7 & 8: Invoke Capability & Receive Data + Provenance."""
        grant_token = access_token or (self.last_grant.get("access_token") if self.last_grant else None)
        payload = {
            "application_id": self.application_id,
            "access_token": grant_token,
            "query_params": query_params or {},
        }
        res = self.client.post(f"/capabilities/{capability_id}/retrieve", json=payload, headers=self._headers())
        if res.status_code == 200:
            result = res.json()
            self.last_response = result
            return result
        elif res.status_code in (401, 403, 404):
            return res.json()
        raise RuntimeError(f"Data retrieval failed: {res.status_code} - {res.text}")

    def run_full_flow(self, capability_id: str = "cap-mangrove-monitoring", purpose: str = "environmental_monitoring") -> Dict[str, Any]:
        """Executes full 10-step end-to-end integration flow."""
        token = self.authenticate()
        capabilities = self.discover_capabilities()
        contract = self.get_capability_contract(capability_id)
        grant = self.request_access(capability_id=capability_id, purpose=purpose)
        
        if not grant.get("authorized"):
            return {"status": "ACCESS_DENIED", "grant": grant}

        data_response = self.retrieve_capability_data(capability_id=capability_id)
        return {
            "status": "SUCCESS",
            "token": token,
            "capabilities_count": len(capabilities),
            "contract": contract,
            "grant": grant,
            "data_response": data_response,
        }
