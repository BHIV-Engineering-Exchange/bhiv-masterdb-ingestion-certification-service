"""
A generic, in-memory, upsert-by-external-id store — shared shape for both
PARIKSHAK's ReviewReference and NIYANTRAN's OperationalTaskState. Upsert
(not append) is what "validate deterministic synchronization" requires:
re-syncing the same external_id twice must produce one current record, not
a growing history of near-duplicates.

Deliberately not disk/DB-backed yet, unlike bcaes_registry/canonical_
repository — this is genuinely new, unconfirmed-contract territory (see
models.py's direction assumption); adding persistence to something that
might need its shape changed once a real PARIKSHAK/NIYANTRAN contract
exists would be persisting a guess. Follows the same pattern
(ArtifactStore/SqlArtifactStore) as everything else here whenever that's
warranted.
"""
from typing import Dict, Generic, List, TypeVar

from pydantic import BaseModel

RecordT = TypeVar("RecordT", bound=BaseModel)


class UpsertSyncStore(Generic[RecordT]):
    def __init__(self) -> None:
        self._records: Dict[str, RecordT] = {}

    def upsert(self, external_id: str, record: RecordT) -> RecordT:
        self._records[external_id] = record
        return record

    def get(self, external_id: str) -> RecordT:
        if external_id not in self._records:
            raise KeyError(external_id)
        return self._records[external_id]

    def list_all(self) -> List[RecordT]:
        return sorted(self._records.values(), key=lambda r: getattr(r, "synced_at"))
