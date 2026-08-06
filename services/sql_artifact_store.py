"""
SqlArtifactStore — a real relational-database-backed implementation of the
same interface `ArtifactStore` (services/artifact_store.py) exposes:
`save`, `load`, `list_all`, `delete`. This is what "MASTERDB will have a
real central database" (task lead, 3 Aug 2026) means concretely: a genuine
SQL engine via SQLAlchemy, not JSON files on disk.

WHY ONE TABLE, JSON-VALUE DESIGN (not a table per registry type): the
records flowing through this store come from eleven different BCAES
registry types plus versioned canonical documents — genuinely
heterogeneous shapes that change as those Pydantic models evolve. A
single `(store_name, key, value_json, updated_at)` table, indexed on
`(store_name, key)`, gives every caller of this store real transactional
writes, real indexed lookups, and a real point to add reporting/analytics
queries later (`SELECT * FROM artifact_records WHERE store_name = ...`)
without a migration for every new field. A normalized per-registry-type
schema is the natural next step once the shapes stabilize — this doesn't
foreclose that, it's what any ORM migration would read from.

WHY THIS DOESN'T CHANGE THE EXTERNAL API SURFACE: `bcaes_registry` and
`canonical_repository`'s routes are still the only way external services
(PRANA, etc.) reach this data — see DATABASE.md for why raw DB
credentials are deliberately not something this service hands out, even
though a real database now exists to hand credentials to.

DEFAULT: SQLite, file-based (`sqlite:///<path>`), zero external
dependencies to try. Point `MASTERDB_DATABASE_URL` at a real Postgres
connection string (`postgresql://...`) for actual production use — this
class doesn't change; SQLAlchemy's dialect handling does.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, String, Text, create_engine, delete as sql_delete, select
from sqlalchemy.orm import DeclarativeBase, Session


class _Base(DeclarativeBase):
    pass


class ArtifactRecord(_Base):
    __tablename__ = "artifact_records"

    store_name: str = Column(String(128), primary_key=True)
    key: str = Column(String(256), primary_key=True)
    value_json: str = Column(Text, nullable=False)
    updated_at: str = Column(DateTime, nullable=False)


class SqlArtifactStore:
    """One instance per logical store (mirrors `ArtifactStore(reports_dir=...)`
    — one instance per directory). `store_name` partitions rows within one
    shared database/table rather than needing one table per caller, so
    `bcaes_registry` and `canonical_repository` can share a single
    `MASTERDB_DATABASE_URL` connection without colliding on keys."""

    def __init__(self, database_url: str, store_name: str) -> None:
        self.database_url = database_url
        self.store_name = store_name
        self._engine = create_engine(database_url, future=True)
        _Base.metadata.create_all(self._engine)

    def save(self, key: str, value: Dict[str, Any]) -> Dict[str, Any]:
        with Session(self._engine) as session:
            existing = session.get(ArtifactRecord, (self.store_name, key))
            payload = json.dumps(value)
            now = datetime.now(timezone.utc)
            if existing is not None:
                existing.value_json = payload
                existing.updated_at = now
            else:
                session.add(
                    ArtifactRecord(store_name=self.store_name, key=key, value_json=payload, updated_at=now)
                )
            session.commit()
        return value

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        with Session(self._engine) as session:
            record = session.get(ArtifactRecord, (self.store_name, key))
            return json.loads(record.value_json) if record else None

    def list_all(self, exclude_prefixes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        exclude_prefixes = exclude_prefixes or []
        with Session(self._engine) as session:
            stmt = select(ArtifactRecord).where(ArtifactRecord.store_name == self.store_name).order_by(
                ArtifactRecord.key
            )
            records = []
            for row in session.execute(stmt).scalars():
                if any(row.key.startswith(prefix) for prefix in exclude_prefixes):
                    continue
                records.append(json.loads(row.value_json))
            return records

    def delete(self, key: str) -> bool:
        with Session(self._engine) as session:
            existing = session.get(ArtifactRecord, (self.store_name, key))
            if existing is None:
                return False
            session.execute(
                sql_delete(ArtifactRecord).where(
                    ArtifactRecord.store_name == self.store_name, ArtifactRecord.key == key
                )
            )
            session.commit()
            return True
