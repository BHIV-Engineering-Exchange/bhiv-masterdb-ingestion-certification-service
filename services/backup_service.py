"""
Backup and recovery.

DESIGN: operates through the same `list_all()` / `save()` interface both
`ArtifactStore` (JSON files) and `SqlArtifactStore` (real database) already
expose — so backup/restore is identical code whether MASTERDB is running
on JSON-file persistence or a real Postgres database. This is the
"backup and recovery" item from the production hardening brief, scoped
honestly: it's an application-level export/import of every record, not a
database-engine-level backup (no `pg_dump`, no WAL archiving — those need
real production infrastructure this environment doesn't have, and are
the natural next step once a real Postgres instance exists to run them
against).

SCOPE LIMIT: only covers services with persistence configured
(`bcaes_registry`, `canonical_repository`) — `operational_sync` has no
persistence layer at all yet (see operational_sync/store.py), so there's
nothing there to back up. A backup taken while a service is running pure
in-memory (`artifact_store` is None) is empty for that service, not an
error — there's genuinely nothing durable to export.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class BackupError(Exception):
    pass


def export_snapshot(stores: Dict[str, Optional[Any]]) -> Dict[str, Any]:
    """`stores` maps a label (e.g. "bcaes_registry") to that service's
    `.artifact_store` (or None if it has no persistence configured)."""
    snapshot: Dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "stores": {},
    }
    for label, store in stores.items():
        if store is None:
            snapshot["stores"][label] = {"persisted": False, "records": []}
        else:
            snapshot["stores"][label] = {"persisted": True, "records": store.list_all()}
    return snapshot


def write_snapshot(snapshot: Dict[str, Any], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(snapshot, indent=2))


def read_snapshot(path: str) -> Dict[str, Any]:
    if not Path(path).exists():
        raise BackupError(f"No backup file at '{path}'.")
    return json.loads(Path(path).read_text())


def restore_snapshot(snapshot: Dict[str, Any], stores: Dict[str, Optional[Any]]) -> Dict[str, int]:
    """Writes every record from the snapshot back into the corresponding
    store via `.save(key, record)`. Requires each target store to already
    be configured with persistence (an in-memory-only service has nowhere
    to restore into) — raises BackupError naming which label failed
    rather than silently skipping it, since a partial, unreported restore
    is worse than a loud failure.

    Note on keys: every record produced by `list_all()` in this repo
    carries its own id as a field (RegistryObject.id,
    CanonicalDocument.id via the "_key"-stripped dict, etc.) — this
    function re-derives the storage key the same way the store originally
    did, per store type, rather than assuming a single universal key
    field name.
    """
    restored_counts: Dict[str, int] = {}
    for label, store_snapshot in snapshot.get("stores", {}).items():
        if not store_snapshot.get("persisted"):
            restored_counts[label] = 0
            continue
        target_store = stores.get(label)
        if target_store is None:
            raise BackupError(
                f"Snapshot has persisted records for '{label}' but no persistence is "
                f"configured for it in this environment — cannot restore into memory-only "
                f"storage. Set the appropriate MASTERDB_STORAGE_DIR/MASTERDB_DATABASE_URL "
                f"first."
            )
        count = 0
        for record in store_snapshot["records"]:
            key = _record_key(label, record)
            target_store.save(key, record)
            count += 1
        restored_counts[label] = count
    return restored_counts


def _record_key(label: str, record: Dict[str, Any]) -> str:
    if label == "canonical_repository":
        return record["document"]["id"]
    if "id" in record:
        return record["id"]
    raise BackupError(f"Don't know how to derive a storage key for a '{label}' record: {record}")
