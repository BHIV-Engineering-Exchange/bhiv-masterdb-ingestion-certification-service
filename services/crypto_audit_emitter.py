"""Immutable cryptographic audit emitter.

Every event is hashed with SHA-256 together with the previous entry's hash,
forming a chain.  Tampering with any entry breaks the chain.

CONCURRENCY & MULTI-WORKER DEPLOYMENT CONSTRAINT:
`CryptoAuditEmitter` uses `threading.Lock` to guarantee thread safety for concurrent
requests within a single OS process.

However, filesystem-backed `ArtifactStore` does not provide distributed inter-process
file locking across multiple OS processes. When running under process-forking application
servers (e.g. `uvicorn --workers N` with N > 1 or Gunicorn worker pools), multiple
independent emitter instances would race on `audit_manifest` and file keys (`audit_entry_...`).

DEPLOYMENT CONSTRAINT:
- File-based persistence (`ArtifactStore` via `MASTERDB_AUDIT_STORE_DIR`) MUST run in a
  single-worker deployment (`uvicorn main:app --workers 1`).
- Multi-worker deployments require an external database-backed store with transactional row
  locking (e.g., PostgreSQL / `SqlArtifactStore`) or a centralized logging daemon.
"""
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


class AuditPersistenceError(RuntimeError):
    """Raised when an audit record or manifest write fails."""

    pass


class AuditCorruptionError(AuditPersistenceError):
    """Raised when persisted audit records or manifest are corrupted or inconsistent."""

    pass


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str
    event_type: str
    actor: str
    payload: Dict[str, Any]
    previous_hash: str
    entry_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor": self.actor,
            "payload": self.payload,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }


class CryptoAuditEmitter:
    def __init__(
        self,
        store: Optional[Any] = None,
        store_dir: Optional[str] = None,
        strict: bool = False,
    ) -> None:
        self._chain: List[AuditEntry] = []
        self._lock = threading.Lock()
        self._is_corrupt: bool = False
        self._corruption_reason: Optional[str] = None

        env = (
            os.environ.get("ENVIRONMENT")
            or os.environ.get("APP_ENV")
            or os.environ.get("MASTERDB_ENV")
            or "development"
        ).strip().lower()
        is_production = env in ("production", "prod")

        try:
            if store is not None:
                self._store = store
            elif store_dir is not None:
                from services.artifact_store import ArtifactStore

                self._store = ArtifactStore(reports_dir=store_dir)
            elif os.environ.get("MASTERDB_AUDIT_STORE_DIR"):
                from services.artifact_store import ArtifactStore

                self._store = ArtifactStore(reports_dir=os.environ["MASTERDB_AUDIT_STORE_DIR"])
            elif os.environ.get("MASTERDB_STORAGE_DIR"):
                storage_dir = os.environ["MASTERDB_STORAGE_DIR"]
                if storage_dir == ":memory:":
                    if is_production:
                        raise RuntimeError(
                            "Configured MASTERDB_STORAGE_DIR is ephemeral (':memory:'). "
                            "A persistent storage directory path is required in production mode."
                        )
                    self._store = None
                else:
                    from services.artifact_store import ArtifactStore

                    self._store = ArtifactStore(reports_dir=os.path.join(storage_dir, "audit_records"))
            elif os.environ.get("MASTERDB_DATABASE_URL"):
                from services.startup_config import is_ephemeral_db_url, sanitize_db_url

                db_url = os.environ["MASTERDB_DATABASE_URL"]
                if not is_ephemeral_db_url(db_url):
                    from services.sql_artifact_store import SqlArtifactStore

                    self._store = SqlArtifactStore(
                        database_url=db_url,
                        store_name="audit_records",
                    )
                elif is_production:
                    sanitized = sanitize_db_url(db_url)
                    raise RuntimeError(
                        f"Configured MASTERDB_DATABASE_URL ('{sanitized}') is ephemeral and cannot be used in production mode."
                    )
                else:
                    self._store = None
            elif is_production:
                raise RuntimeError(
                    "Production mode requires persistent storage configuration: "
                    "MASTERDB_AUDIT_STORE_DIR must be configured in production environment. "
                    "Refusing to run audit emitter in ephemeral in-memory mode."
                )
            else:
                self._store = None

            if is_production and self._store is not None:
                if hasattr(self._store, "ping"):
                    self._store.ping()
        except RuntimeError:
            raise
        except Exception as exc:
            if is_production:
                raise RuntimeError(
                    f"Configured audit store is unusable in production: {exc}"
                ) from exc
            raise

        if self._store is not None:
            with self._lock:
                self._load_from_store(strict=(strict or is_production))

    def _load_from_store(self, strict: bool = False) -> None:
        if self._store is None:
            return
        self._is_corrupt = False
        self._corruption_reason = None

        manifest = self._store.load("audit_manifest")
        expected_count: Optional[int] = None
        manifest_last_hash: Optional[str] = None
        if isinstance(manifest, dict):
            if "count" in manifest:
                try:
                    expected_count = int(manifest["count"])
                except (ValueError, TypeError):
                    self._is_corrupt = True
                    self._corruption_reason = "Malformed count in audit_manifest"
            if "last_hash" in manifest:
                manifest_last_hash = str(manifest["last_hash"])

        loaded: List[AuditEntry] = []
        index = 0
        while True:
            if expected_count is not None and index >= expected_count:
                break
            key = f"audit_entry_{index:08d}"
            record = self._store.load(key)
            if not record:
                if expected_count is not None and index < expected_count:
                    self._is_corrupt = True
                    self._corruption_reason = (
                        f"Incomplete audit store: expected {expected_count} entries according to manifest, "
                        f"but missing record at index {index} ('{key}')."
                    )
                break
            if not isinstance(record, dict):
                self._is_corrupt = True
                self._corruption_reason = f"Invalid record format at index {index} ('{key}')"
                break

            required_fields = ("timestamp", "event_type", "actor", "payload", "previous_hash", "entry_hash")
            if any(field not in record for field in required_fields):
                self._is_corrupt = True
                self._corruption_reason = f"Missing required fields in record at index {index} ('{key}')"
                break

            try:
                entry = AuditEntry(
                    timestamp=str(record["timestamp"]),
                    event_type=str(record["event_type"]),
                    actor=str(record["actor"]),
                    payload=dict(record.get("payload", {})),
                    previous_hash=str(record["previous_hash"]),
                    entry_hash=str(record["entry_hash"]),
                )
                loaded.append(entry)
                index += 1
            except Exception as exc:
                self._is_corrupt = True
                self._corruption_reason = f"Failed to parse record at index {index}: {exc}"
                break

        # Check manifest consistency with loaded entries
        if expected_count is not None and len(loaded) != expected_count:
            self._is_corrupt = True
            if not self._corruption_reason:
                self._corruption_reason = (
                    f"Manifest count mismatch: manifest specified {expected_count} entries, "
                    f"but loaded {len(loaded)} entries."
                )
        elif manifest_last_hash is not None and loaded:
            if loaded[-1].entry_hash != manifest_last_hash:
                self._is_corrupt = True
                if not self._corruption_reason:
                    self._corruption_reason = (
                        f"Manifest last_hash mismatch: manifest specified '{manifest_last_hash}', "
                        f"but last loaded entry has hash '{loaded[-1].entry_hash}'."
                    )

        self._chain = loaded

        if strict and self._is_corrupt:
            raise AuditCorruptionError(self._corruption_reason or "Audit store is corrupted or inconsistent.")

    def reload_from_store(self, strict: bool = False) -> int:
        """Reloads audit chain from persistent store.

        Returns the number of entries in the reloaded chain.
        Raises AuditCorruptionError if strict is True and store is corrupted or incomplete.
        """
        if self._store is None:
            return len(self._chain)
        with self._lock:
            self._load_from_store(strict=strict)
            return len(self._chain)

    @property
    def store(self) -> Optional[Any]:
        return self._store

    @property
    def is_consistent(self) -> bool:
        with self._lock:
            return not self._is_corrupt

    @property
    def corruption_reason(self) -> Optional[str]:
        with self._lock:
            return self._corruption_reason

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

            if self._store is not None:
                idx = len(self._chain)
                record = {
                    "index": idx,
                    "timestamp": entry.timestamp,
                    "event_type": entry.event_type,
                    "actor": entry.actor,
                    "payload": entry.payload,
                    "previous_hash": entry.previous_hash,
                    "entry_hash": entry.entry_hash,
                }
                entry_key = f"audit_entry_{idx:08d}"
                # Step 1: Persist entry record
                try:
                    self._store.save(entry_key, record)
                except Exception as exc:
                    raise AuditPersistenceError(
                        f"Failed to persist audit entry {idx} ('{event_type}'): {exc}"
                    ) from exc

                # Step 2: Persist manifest record
                try:
                    self._store.save(
                        "audit_manifest",
                        {
                            "count": idx + 1,
                            "last_hash": entry.entry_hash,
                        },
                    )
                except Exception as exc:
                    # Clean up orphaned entry on manifest write failure
                    try:
                        self._store.delete(entry_key)
                    except Exception:
                        pass
                    raise AuditPersistenceError(
                        f"Failed to update audit manifest for entry {idx} ('{event_type}'): {exc}"
                    ) from exc

            # Commit to in-memory chain only after successful durable write
            self._chain.append(entry)
            return entry

    def get_chain(self) -> List[AuditEntry]:
        with self._lock:
            return list(self._chain)

    def verify_chain(self) -> bool:
        with self._lock:
            if self._is_corrupt:
                return False
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

            if self._store is not None:
                manifest = self._store.load("audit_manifest")
                if isinstance(manifest, dict):
                    if "count" in manifest and manifest["count"] != len(self._chain):
                        return False
                    if "last_hash" in manifest and self._chain and manifest["last_hash"] != self._chain[-1].entry_hash:
                        return False

            return True

    @property
    def state_hash(self) -> str:
        with self._lock:
            if not self._chain:
                return hashlib.sha256(b"").hexdigest()
            return self._chain[-1].entry_hash
