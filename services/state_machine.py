"""
Deterministic State Machine & Concurrency Control (T-GOV-002).

Manages entity lifecycle transitions, fine-grained concurrency control, rule
evaluation via RuleEngine, and canonical SHA-256 state hashing.
"""
import asyncio
import hashlib
import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set

from evaluation_engine.rule_engine import RuleEngine, RuleResult
from models import PACKAGE_LIFECYCLE_GRAPH, PackageStatus
from models_pravah import PravahEntityType

logger = logging.getLogger("masterdb.state_machine")


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state transition is attempted or a rule fails."""

    def __init__(
        self,
        entity_id: str,
        from_status: PackageStatus,
        to_status: PackageStatus,
        reason: str,
    ) -> None:
        self.entity_id = entity_id
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(
            f"Invalid transition for '{entity_id}' from {from_status.value} to "
            f"{to_status.value}: {reason}"
        )


class EntityState:
    """Logical business state of an ecosystem entity."""

    def __init__(
        self,
        entity_id: str,
        entity_type: PravahEntityType = PravahEntityType.PACKAGE,
        initial_status: PackageStatus = PackageStatus.REGISTERED,
    ) -> None:
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.current_status = initial_status
        self.version = 1
        self.applied_events: List[str] = []
        self.metadata: Dict[str, Any] = {}
        self.transition_log: List[Dict[str, Any]] = []

    def canonical_dict(self) -> Dict[str, Any]:
        """
        Extract the canonical logical state excluding volatile wall-clock
        timestamps, random nonces, and process identifiers.
        """
        return {
            "entity_id": str(self.entity_id),
            "entity_type": self.entity_type.value if hasattr(self.entity_type, "value") else str(self.entity_type),
            "current_status": self.current_status.value if hasattr(self.current_status, "value") else str(self.current_status),
            "version": int(self.version),
            "applied_events": sorted(self.applied_events),
            "metadata": {k: self.metadata[k] for k in sorted(self.metadata.keys())},
        }

    def compute_state_hash(self) -> str:
        """Compute the deterministic SHA-256 hash of the canonical logical state."""
        canonical = self.canonical_dict()
        serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class PravahStateMachine:
    """
    Deterministic state machine coordinating legal lifecycle transitions,
    per-entity concurrency locking, and verification.
    """

    def __init__(
        self,
        rule_engine: Optional[RuleEngine] = None,
        lifecycle_graph: Optional[Dict[PackageStatus, List[PackageStatus]]] = None,
    ) -> None:
        self._states: Dict[str, EntityState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._rule_engine = rule_engine or self._default_rule_engine()
        self._lifecycle_graph = lifecycle_graph or PACKAGE_LIFECYCLE_GRAPH

    @staticmethod
    def _default_rule_engine() -> RuleEngine:
        engine = RuleEngine()
        # Default deterministic evaluation rules for pipeline states
        engine.register_rule(
            PackageStatus.INGESTED.value,
            lambda ctx: bool(ctx.get("source_verified", True)),
        )
        engine.register_rule(
            PackageStatus.VALIDATED.value,
            lambda ctx: float(ctx.get("schema_integrity", 1.0)) >= 0.8,
        )
        engine.register_rule(
            PackageStatus.VERIFIED.value,
            lambda ctx: bool(ctx.get("compliance_verified", True)),
        )
        engine.register_rule(
            PackageStatus.CERTIFIED.value,
            lambda ctx: float(ctx.get("certification_score", 100.0)) >= 70.0,
        )
        engine.register_rule(
            PackageStatus.RETRIEVAL_READY.value,
            lambda ctx: bool(ctx.get("contract_published", True)),
        )
        engine.register_rule(
            PackageStatus.DEPRECATED.value,
            lambda ctx: True,
        )
        engine.register_rule(
            PackageStatus.ARCHIVED.value,
            lambda ctx: True,
        )
        return engine

    def _get_lock(self, entity_id: str) -> asyncio.Lock:
        if entity_id not in self._locks:
            self._locks[entity_id] = asyncio.Lock()
        return self._locks[entity_id]

    def get_or_create_state(
        self,
        entity_id: str,
        entity_type: PravahEntityType = PravahEntityType.PACKAGE,
        initial_status: PackageStatus = PackageStatus.REGISTERED,
    ) -> EntityState:
        if entity_id not in self._states:
            self._states[entity_id] = EntityState(
                entity_id=entity_id,
                entity_type=entity_type,
                initial_status=initial_status,
            )
        return self._states[entity_id]

    def get_state(self, entity_id: str) -> Optional[EntityState]:
        return self._states.get(entity_id)

    async def transition(
        self,
        entity_id: str,
        target_status: PackageStatus,
        event_id: str,
        context: Optional[Dict[str, Any]] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> EntityState:
        """
        Execute an atomic, serialized state transition protected by an entity-level lock.
        Validates lifecycle graph edges and evaluates RuleEngine rules.
        """
        lock = self._get_lock(entity_id)
        async with lock:
            state = self.get_or_create_state(entity_id)

            # Idempotency: if this event_id was already applied to this entity, return current state
            if event_id in state.applied_events:
                logger.info(
                    "Event '%s' already applied to entity '%s'. Returning idempotent state.",
                    event_id,
                    entity_id,
                )
                return state

            current = state.current_status

            # Check if transition is legal in the lifecycle graph
            allowed = self._lifecycle_graph.get(current, [])
            if target_status not in allowed and target_status != current:
                allowed_str = ", ".join(s.value for s in allowed)
                raise InvalidStateTransitionError(
                    entity_id=entity_id,
                    from_status=current,
                    to_status=target_status,
                    reason=f"Transition not allowed in lifecycle graph. Allowed targets: [{allowed_str}]",
                )

            # Evaluate transition rule in RuleEngine
            ctx = context or {}
            rule_result: RuleResult = self._rule_engine.evaluate(ctx, target_status.value)
            if not rule_result.passed:
                raise InvalidStateTransitionError(
                    entity_id=entity_id,
                    from_status=current,
                    to_status=target_status,
                    reason=f"Rule check failed: {rule_result.reason}",
                )

            # Apply state mutation deterministically
            state.current_status = target_status
            state.version += 1
            state.applied_events.append(event_id)
            if metadata_updates:
                state.metadata.update(metadata_updates)

            state.transition_log.append(
                {
                    "event_id": event_id,
                    "from_status": current.value,
                    "to_status": target_status.value,
                    "rule_result": asdict(rule_result),
                    "version": state.version,
                }
            )

            logger.info(
                "Entity '%s' successfully transitioned %s -> %s (v%d)",
                entity_id,
                current.value,
                target_status.value,
                state.version,
            )
            return state

    def clear(self) -> None:
        """Reset state machine for testing."""
        self._states.clear()
        self._locks.clear()
