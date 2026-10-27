"""
Asynchronous Event-Driven Pipeline & Replay Orchestrator (T-GOV-002).

Orchestrates Pravah events, replay ledgers, deterministic state machines,
audit chains, and external event dispatch.
"""
import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from integrations.pravah_client import PravahClient
from models import PACKAGE_LIFECYCLE_GRAPH, PackageStatus
from models_pravah import (
    PipelineExecutionRequest,
    PipelineExecutionResponse,
    PravahEvent,
    PravahEventStatus,
    PravahEventType,
    PravahLedgerEntry,
    ReplayRequest,
    ReplayResponse,
    _new_id,
    _utcnow,
)
from services.crypto_audit_emitter import CryptoAuditEmitter
from services.pravah_ledger import PravahReplayLedger
from services.state_machine import EntityState, InvalidStateTransitionError, PravahStateMachine

logger = logging.getLogger("masterdb.event_pipeline")


class EventPipeline:
    """
    Unified asynchronous event-driven pipeline coordinating replay ledgers,
    concurrency control, state machines, and cryptographic audit chains.
    """

    def __init__(
        self,
        ledger: Optional[PravahReplayLedger] = None,
        state_machine: Optional[PravahStateMachine] = None,
        audit_emitter: Optional[CryptoAuditEmitter] = None,
        pravah_client: Optional[PravahClient] = None,
    ) -> None:
        self.ledger = ledger or PravahReplayLedger()
        self.state_machine = state_machine or PravahStateMachine()
        self.audit_emitter = audit_emitter or CryptoAuditEmitter()
        self.pravah_client = pravah_client or PravahClient()

    async def process_event(
        self,
        event: PravahEvent,
    ) -> Tuple[PravahLedgerEntry, EntityState]:
        """
        Ingest, record, and process an event asynchronously.
        Guarantees deduplication, strict concurrency control, and audit trail emission.
        """
        # Step 1: Record event in ledger
        entry = self.ledger.record_event(event)

        # Check for duplicate
        state = self.state_machine.get_or_create_state(
            entity_id=event.entity_id,
            entity_type=event.entity_type,
        )

        if event.event_id in state.applied_events:
            logger.info("Idempotent event '%s' ignored; returning current state.", event.event_id)
            return entry, state

        # Step 2: Determine target status if applicable
        target = event.target_status
        if not target and event.event_type == PravahEventType.INGESTION_REQUESTED:
            target = PackageStatus.INGESTED
        elif not target and event.event_type == PravahEventType.VALIDATION_COMPLETED:
            target = PackageStatus.VALIDATED
        elif not target and event.event_type == PravahEventType.VERIFICATION_COMPLETED:
            target = PackageStatus.VERIFIED
        elif not target and event.event_type == PravahEventType.CERTIFICATION_GRANTED:
            target = PackageStatus.CERTIFIED

        # Step 3: Transition state machine if target state is specified
        if target:
            try:
                state = await self.state_machine.transition(
                    entity_id=event.entity_id,
                    target_status=target,
                    event_id=event.event_id,
                    context=event.payload,
                    metadata_updates=event.payload.get("metadata"),
                )
            except InvalidStateTransitionError as exc:
                self.ledger.fail_entry(entry.sequence_number, str(exc))
                self.audit_emitter.emit(
                    event_type="pravah_event_failed",
                    actor=event.producer,
                    payload={
                        "event_id": event.event_id,
                        "sequence_number": entry.sequence_number,
                        "error": str(exc),
                    },
                )
                raise

        # Step 4: Commit ledger entry with deterministic state hash
        current_hash = state.compute_state_hash()
        committed_entry = self.ledger.commit_entry(
            sequence_number=entry.sequence_number,
            state_hash_after=current_hash,
        )

        # Step 5: Emit cryptographic audit entry
        self.audit_emitter.emit(
            event_type="pravah_event_committed",
            actor=event.producer,
            payload={
                "event_id": event.event_id,
                "sequence_number": committed_entry.sequence_number,
                "entity_id": event.entity_id,
                "status": state.current_status.value,
                "state_hash": current_hash,
            },
        )

        # Step 6: Dispatch downstream event
        try:
            self.pravah_client.publish_event(event)
        except Exception as exc:
            logger.warning("Downstream Pravah notification warning: %s", exc)

        return committed_entry, state

    async def replay_ledger(
        self,
        request: ReplayRequest,
    ) -> ReplayResponse:
        """
        Replay eligible events from the ledger.
        Ensures replay idempotency and asserts consistent state progression.
        """
        entries = self.ledger.get_replay_stream(
            from_sequence=request.from_sequence,
            to_sequence=request.to_sequence,
            topic=request.topic,
            entity_id=request.entity_id,
        )

        replayed_count = 0
        skipped_duplicate_count = 0
        failed_count = 0

        for entry in entries:
            event = entry.event
            state = self.state_machine.get_or_create_state(
                entity_id=event.entity_id,
                entity_type=event.entity_type,
            )

            # Check if event was already applied
            if event.event_id in state.applied_events:
                skipped_duplicate_count += 1
                continue

            try:
                target = event.target_status
                if target:
                    await self.state_machine.transition(
                        entity_id=event.entity_id,
                        target_status=target,
                        event_id=event.event_id,
                        context=event.payload,
                        metadata_updates=event.payload.get("metadata"),
                    )
                replayed_count += 1
            except Exception as exc:
                logger.error("Error during replay of event %s: %s", event.event_id, exc)
                failed_count += 1

        entity_id = request.entity_id or (entries[0].event.entity_id if entries else "unknown")
        final_state = self.state_machine.get_state(entity_id)
        final_hash = final_state.compute_state_hash() if final_state else "0" * 64

        return ReplayResponse(
            replayed_count=replayed_count,
            skipped_duplicate_count=skipped_duplicate_count,
            failed_count=failed_count,
            state_hash=final_hash,
            entries=entries,
        )

    async def execute_pipeline(
        self,
        request: PipelineExecutionRequest,
    ) -> PipelineExecutionResponse:
        """
        Automate the full ecosystem pipeline from initial_status to target_status.
        Walks shortest path through PACKAGE_LIFECYCLE_GRAPH, generates and commits
        events into the Pravah replay ledger, and records full audit trail.
        """
        pipeline_id = _new_id("pipe")
        path = self._find_lifecycle_path(request.initial_status, request.target_status)
        if not path:
            raise InvalidStateTransitionError(
                entity_id=request.entity_id,
                from_status=request.initial_status,
                to_status=request.target_status,
                reason="No legal lifecycle path between initial and target status",
            )

        state = self.state_machine.get_or_create_state(
            entity_id=request.entity_id,
            entity_type=request.entity_type,
            initial_status=request.initial_status,
        )
        if request.metadata:
            state.metadata.update(request.metadata)

        transitions: List[Dict[str, Any]] = []
        seq_start = self.ledger.total_count() + 1

        for next_status in path[1:]:
            event_type = self._map_status_to_event_type(next_status)
            event = PravahEvent(
                event_id=_new_id("evt"),
                topic="pravah.masterdb.pipeline",
                event_type=event_type,
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                producer=request.actor,
                target_status=next_status,
                payload=request.context,
                correlation_id=pipeline_id,
            )

            entry, state = await self.process_event(event)
            transitions.append(
                {
                    "from_status": state.transition_log[-1]["from_status"] if state.transition_log else request.initial_status.value,
                    "to_status": next_status.value,
                    "event_id": event.event_id,
                    "sequence_number": entry.sequence_number,
                    "version": state.version,
                }
            )

        seq_end = self.ledger.total_count()
        final_hash = state.compute_state_hash()
        audit_entry = self.audit_emitter.emit(
            event_type="pipeline_execution_completed",
            actor=request.actor,
            payload={
                "pipeline_id": pipeline_id,
                "entity_id": request.entity_id,
                "final_status": state.current_status.value,
                "transitions_count": len(transitions),
                "state_hash": final_hash,
            },
        )

        return PipelineExecutionResponse(
            pipeline_id=pipeline_id,
            entity_id=request.entity_id,
            final_status=state.current_status,
            success=True,
            transitions=transitions,
            state_hash=final_hash,
            ledger_sequence_start=seq_start,
            ledger_sequence_end=seq_end,
            audit_entry_hash=audit_entry.entry_hash,
        )

    @staticmethod
    def _find_lifecycle_path(
        start: PackageStatus,
        goal: PackageStatus,
    ) -> Optional[List[PackageStatus]]:
        """Breadth-first search for valid status path."""
        if start == goal:
            return [start]
        queue: List[List[PackageStatus]] = [[start]]
        visited = {start}
        while queue:
            current_path = queue.pop(0)
            node = current_path[-1]
            for neighbor in PACKAGE_LIFECYCLE_GRAPH.get(node, []):
                if neighbor == goal:
                    return current_path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(current_path + [neighbor])
        return None

    @staticmethod
    def _map_status_to_event_type(status: PackageStatus) -> PravahEventType:
        mapping = {
            PackageStatus.INGESTED: PravahEventType.INGESTION_REQUESTED,
            PackageStatus.VALIDATED: PravahEventType.VALIDATION_COMPLETED,
            PackageStatus.VERIFIED: PravahEventType.VERIFICATION_COMPLETED,
            PackageStatus.CERTIFIED: PravahEventType.CERTIFICATION_GRANTED,
            PackageStatus.RETRIEVAL_READY: PravahEventType.STATUS_CHANGED,
            PackageStatus.DEPRECATED: PravahEventType.STATUS_CHANGED,
            PackageStatus.ARCHIVED: PravahEventType.STATUS_CHANGED,
        }
        return mapping.get(status, PravahEventType.STATUS_CHANGED)
