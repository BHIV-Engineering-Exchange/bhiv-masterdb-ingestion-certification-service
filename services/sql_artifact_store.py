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
without a migration for every new field.

TARGET DATASET PERSISTENCE:
Additionally provides target database tables `target_datasets` and
`target_dataset_records` so that when ingestion succeeds, the actual
dataset records are physically persisted in the database via atomic
SQL transactions and are retrievable.

DEFAULT: SQLite, file-based (`sqlite:///<path>`), zero external
dependencies to try. Point `DATABASE_URL` or `MASTERDB_DATABASE_URL` at a real Postgres
connection string (`postgresql://...`) for actual production use — this
class doesn't change; SQLAlchemy's dialect handling does.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    delete as sql_delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session


class _Base(DeclarativeBase):
    pass


class ArtifactRecord(_Base):
    __tablename__ = "artifact_records"

    store_name: str = Column(String(128), primary_key=True)
    key: str = Column(String(256), primary_key=True)
    value_json: str = Column(Text, nullable=False)
    updated_at: str = Column(DateTime, nullable=False)


class TargetDatasetSummary(_Base):
    __tablename__ = "target_datasets"

    id: str = Column(String(256), primary_key=True)  # f"{target_database}:{dataset_id}"
    target_database: str = Column(String(64), index=True, nullable=False)
    dataset_id: str = Column(String(128), index=True, nullable=False)
    record_count: int = Column(Integer, nullable=False)
    source_format: str = Column(String(32), nullable=False)
    status: str = Column(String(32), nullable=False, default="PERSISTED")
    metadata_json: Optional[str] = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class TargetDatasetRecord(_Base):
    __tablename__ = "target_dataset_records"

    id: str = Column(String(256), primary_key=True)  # f"{target_database}:{dataset_id}:{row_index}"
    target_database: str = Column(String(64), index=True, nullable=False)
    dataset_id: str = Column(String(128), index=True, nullable=False)
    row_index: int = Column(Integer, nullable=False)
    record_json: str = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)


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

    # -- Target Dataset Persistence -------------------------------------------

    def persist_target_dataset(
        self,
        target_database: str,
        dataset_id: str,
        source_format: str,
        records: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Atomically persist target dataset records into the database within a transaction."""
        now = datetime.now(timezone.utc)
        summary_id = f"{target_database}:{dataset_id}"
        with Session(self._engine) as session:
            try:
                # Delete existing rows for this target_database and dataset_id (idempotent replace)
                session.execute(
                    sql_delete(TargetDatasetRecord).where(
                        TargetDatasetRecord.target_database == target_database,
                        TargetDatasetRecord.dataset_id == dataset_id,
                    )
                )
                existing_summary = session.get(TargetDatasetSummary, summary_id)
                if existing_summary is not None:
                    existing_summary.record_count = len(records)
                    existing_summary.source_format = source_format
                    existing_summary.status = "PERSISTED"
                    existing_summary.metadata_json = json.dumps(metadata or {})
                    existing_summary.updated_at = now
                else:
                    session.add(
                        TargetDatasetSummary(
                            id=summary_id,
                            target_database=target_database,
                            dataset_id=dataset_id,
                            record_count=len(records),
                            source_format=source_format,
                            status="PERSISTED",
                            metadata_json=json.dumps(metadata or {}),
                            created_at=now,
                            updated_at=now,
                        )
                    )

                # Insert individual records
                for idx, record in enumerate(records):
                    rec_id = f"{target_database}:{dataset_id}:{idx}"
                    session.add(
                        TargetDatasetRecord(
                            id=rec_id,
                            target_database=target_database,
                            dataset_id=dataset_id,
                            row_index=idx,
                            record_json=json.dumps(record),
                            created_at=now,
                        )
                    )
                session.commit()
            except Exception:
                session.rollback()
                raise

        # Also store artifact record summary in artifact_records for fast lookup
        self.save(
            f"{target_database}:{dataset_id}",
            {
                "target_database": target_database,
                "dataset_id": dataset_id,
                "record_count": len(records),
                "source_format": source_format,
                "status": "PERSISTED",
                "metadata": metadata or {},
                "persisted_at": now.isoformat(),
            },
        )

        return {
            "target_database": target_database,
            "dataset_id": dataset_id,
            "record_count": len(records),
            "status": "PERSISTED",
            "target_reference": f"{target_database}/{dataset_id}",
        }

    def get_target_dataset(self, target_database: str, dataset_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve target dataset summary from database."""
        summary_id = f"{target_database}:{dataset_id}"
        with Session(self._engine) as session:
            summary = session.get(TargetDatasetSummary, summary_id)
            if summary is None:
                return None
            return {
                "target_database": summary.target_database,
                "dataset_id": summary.dataset_id,
                "record_count": summary.record_count,
                "source_format": summary.source_format,
                "status": summary.status,
                "metadata": json.loads(summary.metadata_json) if summary.metadata_json else {},
                "created_at": summary.created_at.isoformat() if hasattr(summary.created_at, "isoformat") else str(summary.created_at),
                "updated_at": summary.updated_at.isoformat() if hasattr(summary.updated_at, "isoformat") else str(summary.updated_at),
            }

    def list_target_records(
        self, target_database: str, dataset_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Retrieve target dataset rows from database with pagination."""
        with Session(self._engine) as session:
            stmt = (
                select(TargetDatasetRecord)
                .where(
                    TargetDatasetRecord.target_database == target_database,
                    TargetDatasetRecord.dataset_id == dataset_id,
                )
                .order_by(TargetDatasetRecord.row_index)
                .offset(offset)
                .limit(limit)
            )
            records = []
            for row in session.execute(stmt).scalars():
                records.append(json.loads(row.record_json))
            return records
