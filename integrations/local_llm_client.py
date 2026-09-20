"""Local LLM client with circuit-breaker protection.

Wraps a local inference endpoint with the existing CircuitBreaker.
"""
import os
from typing import Any, Dict, Optional

import requests
from pydantic import BaseModel, ConfigDict, Field

from middleware.circuit_breaker import CircuitBreaker, CircuitBreakerError


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str
    context: Dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: str
    model: str = "unknown"


class LocalLLMClient:
    def __init__(self, endpoint: Optional[str] = None, timeout: float = 30.0) -> None:
        self.endpoint = endpoint or os.environ.get("LOCAL_LLM_ENDPOINT", "")
        self.timeout = timeout
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            timeout_seconds=60.0,
            expected_exceptions=(requests.RequestException,),
        )

    def is_configured(self) -> bool:
        return bool(self.endpoint)

    def analyze(self, request: LLMRequest) -> LLMResponse:
        if not self.is_configured():
            raise RuntimeError("Local LLM endpoint not configured")

        def _call() -> LLMResponse:
            resp = requests.post(
                f"{self.endpoint}/analyze",
                json=request.model_dump(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                result=data.get("result", ""),
                model=data.get("model", "unknown"),
            )

        try:
            return self._circuit_breaker.call(_call)
        except CircuitBreakerError as exc:
            raise RuntimeError(f"Circuit breaker open: {exc}") from exc
