"""Immutable cryptographic audit emitter.

Every event is hashed with SHA-256 together with the previous entry's hash,
forming a chain.  Tampering with any entry breaks the chain.
"""
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import threading


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str
    event_type: str
    actor: str
    payload: Dict[str, Any]
    previous_hash: str
    entry_hash: str


class CryptoAuditEmitter:
    def __init__(self) -> None:
        self._chain: List[AuditEntry] = []
        self._lock = threading.Lock()

    def emit(
        self,
        event_type: str,
        actor: str,
        payload: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            previous_hash = self._chain[-1].entry_hash if self._chain else "0" * 64
            data = json.dumps(
                {
                    "timestamp": timestamp,
                    "event_type": event_type,
                    "actor": actor,
                    "payload": payload,
                    "previous_hash": previous_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            entry_hash = hashlib.sha256(data.encode("utf-8")).hexdigest()
            entry = AuditEntry(
                timestamp=timestamp,
                event_type=event_type,
                actor=actor,
                payload=payload,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
            )
            self._chain.append(entry)
            return entry

    def get_chain(self) -> List[AuditEntry]:
        with self._lock:
            return list(self._chain)

    def verify_chain(self) -> bool:
        with self._lock:
            for i, entry in enumerate(self._chain):
                expected_prev = self._chain[i - 1].entry_hash if i > 0 else "0" * 64
                if entry.previous_hash != expected_prev:
                    return False
                data = json.dumps(
                    {
                        "timestamp": entry.timestamp,
                        "event_type": entry.event_type,
                        "actor": entry.actor,
                        "payload": entry.payload,
                        "previous_hash": entry.previous_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                expected_hash = hashlib.sha256(data.encode("utf-8")).hexdigest()
                if entry.entry_hash != expected_hash:
                    return False
            return True

    @property
    def state_hash(self) -> str:
        with self._lock:
            if not self._chain:
                return hashlib.sha256(b"").hexdigest()
            return self._chain[-1].entry_hash
