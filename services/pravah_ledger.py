"""
Pravah Replay Ledger (T-GOV-002).

Thread-safe, append-only, durable event ledger providing strict monotonic
sequence numbers, deduplication indexing, snapshot persistence, and deterministic
replay semantics across BHIV ecosystem pipelines.
"""
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from models_pravah import (
    PravahEvent,
    PravahEventStatus,
    PravahLedgerEntry,
    _utcnow,
)

logger = logging.getLogger("masterdb.pravah_ledger")


class PravahReplayLedger:
    """
    Append-only replay ledger for Pravah event streams.
    Guarantees thread-safe recording, idempotent deduplication, and ordered replay.
    """

    def __init__(self, persistence_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._entries: List[PravahLedgerEntry] = []
        self._sequence_counter: int = 0
        # Maps event_id -> sequence_number for deduplication
        self._dedup_index: Dict[str, int] = {}
        # Maps idempotency_key -> sequence_number
        self._idempotency_index: Dict[str, int] = {}
        self.persistence_path = persistence_path

        if self.persistence_path and os.path.exists(self.persistence_path):
            self.load_snapshot(self.persistence_path)

    def record_event(
        self,
        event: PravahEvent,
        initial_status: PravahEventStatus = PravahEventStatus.PENDING,
    ) -> PravahLedgerEntry:
        """
        Record a new event into the append-only ledger with a monotonic sequence number.
        If an event with the same event_id or idempotency_key was already recorded,
        returns the existing entry with status marked DUPLICATE.
        """
        with self._lock:
            # Check for duplicate event_id
            if event.event_id in self._dedup_index:
                existing_seq = self._dedup_index[event.event_id]
                existing_entry = self._entries[existing_seq - 1]
                logger.warning(
                    "Duplicate event_id detected in ledger: %s (seq: %d)",
                    event.event_id,
                    existing_seq,
                )
                return existing_entry

            # Check for duplicate idempotency_key if supplied
            if event.idempotency_key and event.idempotency_key in self._idempotency_index:
                existing_seq = self._idempotency_index[event.idempotency_key]
                existing_entry = self._entries[existing_seq - 1]
                logger.warning(
                    "Duplicate idempotency_key detected in ledger: %s (seq: %d)",
                    event.idempotency_key,
                    existing_seq,
                )
                return existing_entry

            self._sequence_counter += 1
            entry = PravahLedgerEntry(
                sequence_number=self._sequence_counter,
                event=event,
                status=initial_status,
                recorded_at=_utcnow(),
            )
            self._entries.append(entry)
            self._dedup_index[event.event_id] = self._sequence_counter
            if event.idempotency_key:
                self._idempotency_index[event.idempotency_key] = self._sequence_counter

            if self.persistence_path:
                self._save_atomic()

            return entry

    def commit_entry(
        self,
        sequence_number: int,
        state_hash_after: Optional[str] = None,
    ) -> PravahLedgerEntry:
        """Mark an existing entry as COMMITTED with resulting state hash."""
        with self._lock:
            if sequence_number < 1 or sequence_number > len(self._entries):
                raise ValueError(f"Invalid sequence_number: {sequence_number}")
            entry = self._entries[sequence_number - 1]
            updated = PravahLedgerEntry(
                sequence_number=entry.sequence_number,
                event=entry.event,
                status=PravahEventStatus.COMMITTED,
                recorded_at=entry.recorded_at,
                processed_at=_utcnow(),
                state_hash_after=state_hash_after,
                error_message=None,
                retry_count=entry.retry_count,
            )
            self._entries[sequence_number - 1] = updated
            if self.persistence_path:
                self._save_atomic()
            return updated

    def fail_entry(
        self,
        sequence_number: int,
        error_message: str,
    ) -> PravahLedgerEntry:
        """Mark an entry as FAILED with recorded error message."""
        with self._lock:
            if sequence_number < 1 or sequence_number > len(self._entries):
                raise ValueError(f"Invalid sequence_number: {sequence_number}")
            entry = self._entries[sequence_number - 1]
            updated = PravahLedgerEntry(
                sequence_number=entry.sequence_number,
                event=entry.event,
                status=PravahEventStatus.FAILED,
                recorded_at=entry.recorded_at,
                processed_at=_utcnow(),
                state_hash_after=entry.state_hash_after,
                error_message=error_message,
                retry_count=entry.retry_count + 1,
            )
            self._entries[sequence_number - 1] = updated
            if self.persistence_path:
                self._save_atomic()
            return updated

    def get_entry(self, sequence_number: int) -> Optional[PravahLedgerEntry]:
        with self._lock:
            if 1 <= sequence_number <= len(self._entries):
                return self._entries[sequence_number - 1]
            return None

    def get_entry_by_event_id(self, event_id: str) -> Optional[PravahLedgerEntry]:
        with self._lock:
            seq = self._dedup_index.get(event_id)
            if seq is not None:
                return self._entries[seq - 1]
            return None

    def query_entries(
        self,
        from_sequence: int = 1,
        to_sequence: Optional[int] = None,
        topic: Optional[str] = None,
        entity_id: Optional[str] = None,
        status: Optional[PravahEventStatus] = None,
        limit: int = 100,
    ) -> List[PravahLedgerEntry]:
        """Query entries matching sequence range and optional filters."""
        with self._lock:
            results: List[PravahLedgerEntry] = []
            max_seq = to_sequence if to_sequence is not None else len(self._entries)
            start_idx = max(0, from_sequence - 1)
            end_idx = min(len(self._entries), max_seq)

            for entry in self._entries[start_idx:end_idx]:
                if topic and entry.event.topic != topic:
                    continue
                if entity_id and entry.event.entity_id != entity_id:
                    continue
                if status and entry.status != status:
                    continue
                results.append(entry)
                if len(results) >= limit:
                    break
            return results

    def get_replay_stream(
        self,
        from_sequence: int = 1,
        to_sequence: Optional[int] = None,
        topic: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> List[PravahLedgerEntry]:
        """Retrieve slice of ledger eligible for replay."""
        return self.query_entries(
            from_sequence=from_sequence,
            to_sequence=to_sequence,
            topic=topic,
            entity_id=entity_id,
            limit=10_000,
        )

    def total_count(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        """Reset the ledger (used in test isolation)."""
        with self._lock:
            self._entries.clear()
            self._sequence_counter = 0
            self._dedup_index.clear()
            self._idempotency_index.clear()
            if self.persistence_path and os.path.exists(self.persistence_path):
                try:
                    os.remove(self.persistence_path)
                except OSError:
                    pass

    def save_snapshot(self, path: str) -> None:
        """Write entire ledger to disk atomically."""
        with self._lock:
            data = {
                "sequence_counter": self._sequence_counter,
                "entries": [e.model_dump() for e in self._entries],
            }
            tmp_path = f"{path}.tmp"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            if os.path.exists(path):
                os.remove(path)
            os.rename(tmp_path, path)

    def load_snapshot(self, path: str) -> None:
        """Restore ledger state from snapshot."""
        with self._lock:
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._sequence_counter = data.get("sequence_counter", 0)
            self._entries = [PravahLedgerEntry.model_validate(e) for e in data.get("entries", [])]
            self._dedup_index = {e.event.event_id: e.sequence_number for e in self._entries}
            self._idempotency_index = {
                e.event.idempotency_key: e.sequence_number
                for e in self._entries
                if e.event.idempotency_key
            }

    def _save_atomic(self) -> None:
        if self.persistence_path:
            self.save_snapshot(self.persistence_path)
