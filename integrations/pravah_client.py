"""
Pravah Event Bus Integration Adapter (T-GOV-002).

Provides an upstream/downstream client for Pravah event-driven messaging,
complete with circuit-breaker protection, timeout controls, and simulated test doubles.
"""
import logging
import os
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, ConfigDict, Field

from middleware.circuit_breaker import CircuitBreaker, CircuitBreakerError
from models_pravah import PravahEvent

logger = logging.getLogger("masterdb.pravah_client")


class PravahPublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    event_id: str
    topic: str
    partition: int = 0
    simulated: bool = False


class PravahClient:
    """
    Client adapter for Pravah event streaming infrastructure.
    If PRAVAH_BHIV_CORE_EVENTS or PRAVAH_BHIV_CORE is configured, dispatches
    live HTTP events. Otherwise operates as a verified deterministic test double.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.endpoint = (
            endpoint
            if endpoint is not None
            else os.environ.get("PRAVAH_BHIV_CORE_EVENTS") or os.environ.get("PRAVAH_BHIV_CORE") or ""
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds

        self._circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.environ.get("PRAVAH_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")),
            timeout_seconds=float(os.environ.get("PRAVAH_CIRCUIT_BREAKER_TIMEOUT_SECONDS", "30.0")),
            expected_exceptions=(requests.RequestException,),
        )
        self._published_events: List[PravahEvent] = []

    def is_configured(self) -> bool:
        return bool(self.endpoint)

    def publish_event(self, event: PravahEvent) -> PravahPublishResponse:
        """
        Publish an event to Pravah.
        Uses circuit breaker when communicating with a real endpoint;
        falls back cleanly to simulated recording if unconfigured.
        """
        self._published_events.append(event)

        if not self.is_configured():
            logger.info(
                "Pravah unconfigured; recorded event '%s' to simulated bus (topic: %s)",
                event.event_id,
                event.topic,
            )
            return PravahPublishResponse(
                status="published_simulated",
                event_id=event.event_id,
                topic=event.topic,
                partition=0,
                simulated=True,
            )

        def _dispatch() -> PravahPublishResponse:
            url = f"{self.endpoint}/api/v1/events"
            resp = requests.post(
                url,
                json=event.model_dump(),
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            return PravahPublishResponse(
                status=data.get("status", "published"),
                event_id=event.event_id,
                topic=event.topic,
                partition=data.get("partition", 0),
                simulated=False,
            )

        try:
            return self._circuit_breaker.call(_dispatch)
        except CircuitBreakerError as exc:
            logger.warning("Pravah circuit breaker open: %s", exc)
            return PravahPublishResponse(
                status="circuit_breaker_open",
                event_id=event.event_id,
                topic=event.topic,
                partition=-1,
                simulated=True,
            )
        except Exception as exc:
            logger.error("Failed to publish event to Pravah: %s", exc)
            raise

    def get_published_events(self) -> List[PravahEvent]:
        return list(self._published_events)

    def clear(self) -> None:
        self._published_events.clear()
