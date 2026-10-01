from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class ArtifactStore:
    def __init__(self, reports_dir: str = "reports") -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def report_path(self, dataset_id: str) -> Path:
        return self.reports_dir / f"{dataset_id}.json"

    def save(self, dataset_id: str, report: Dict[str, Any]) -> Dict[str, Any]:
        path = self.report_path(dataset_id)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=4)
        return report

    def load(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        path = self.report_path(dataset_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def delete(self, dataset_id: str) -> bool:
        """Returns True if a record existed and was removed, False if there
        was nothing to delete. Added so callers (bcaes_registry/store.py)
        don't reach into Path.unlink() directly — that coupled them to this
        being file-backed, which stopped being true once SqlArtifactStore
        (services/sql_artifact_store.py) existed as an alternative backend."""
        path = self.report_path(dataset_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self, exclude_prefixes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Load every record in this store. Used by discovery/query surfaces
        that need to scan-and-filter rather than point-lookup by key.

        `exclude_prefixes` skips convenience index keys (e.g. a secondary
        "by-package-*" index) so callers don't double-count a record stored
        under two keys.

        Deterministic ordering: results are sorted by filename so repeated
        calls against the same on-disk state always return the same order,
        which matters for replayable discovery responses.
        """
        exclude_prefixes = exclude_prefixes or []
        records: List[Dict[str, Any]] = []
        for path in sorted(self.reports_dir.glob("*.json")):
            key = path.stem
            if any(key.startswith(prefix) for prefix in exclude_prefixes):
                continue
            with path.open("r", encoding="utf-8") as handle:
                records.append(json.load(handle))
        return records

    def persist_target_dataset(
        self,
        target_database: str,
        dataset_id: str,
        source_format: str,
        records: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist target dataset records into the file store."""
        target_dir = self.reports_dir / "target_data" / target_database
        target_dir.mkdir(parents=True, exist_ok=True)
        dataset_file = target_dir / f"{dataset_id}.json"
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "target_database": target_database,
            "dataset_id": dataset_id,
            "record_count": len(records),
            "source_format": source_format,
            "status": "PERSISTED",
            "metadata": metadata or {},
            "records": records,
            "created_at": now,
            "updated_at": now,
        }
        with dataset_file.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        return {
            "target_database": target_database,
            "dataset_id": dataset_id,
            "record_count": len(records),
            "status": "PERSISTED",
            "target_reference": f"{target_database}/{dataset_id}",
        }

    def get_target_dataset(self, target_database: str, dataset_id: str) -> Optional[Dict[str, Any]]:
        dataset_file = self.reports_dir / "target_data" / target_database / f"{dataset_id}.json"
        if not dataset_file.exists():
            return None
        with dataset_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if k != "records"}

    def list_target_records(
        self, target_database: str, dataset_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        dataset_file = self.reports_dir / "target_data" / target_database / f"{dataset_id}.json"
        if not dataset_file.exists():
            return []
        with dataset_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        records = data.get("records", [])
        return records[offset : offset + limit]


