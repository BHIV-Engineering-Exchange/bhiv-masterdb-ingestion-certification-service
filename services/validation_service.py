import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

from engines.classification_engine import ClassificationEngine
from engines.recommendation_engine import RecommendationEngine
from engines.risk_engine import RiskEngine
from engines.scoring_engine import ScoringEngine
from models import CertificationState
from profiling.dataset_profiler import DatasetProfiler
from security.path_resolution import WORKSPACE_ROOT, resolve_secure_path
from services.artifact_store import ArtifactStore
from utils.loader import DatasetLoader
from validators.completeness_validator import CompletenessValidator
from validators.consistency_validator import ConsistencyValidator
from validators.duplicate_validator import DuplicateValidator
from validators.integrity_boundary_validator import IntegrityBoundaryValidator
from validators.metadata_validator import MetadataValidator
from validators.provenance_validator import ProvenanceValidator
from validators.schema_validator import SchemaValidator


class ValidationService:
    def __init__(
        self,
        schema_path: str = "config/schema.json",
        rules_path: str = "config/validation_rules.json",
        artifact_store: Optional[ArtifactStore] = None,
    ) -> None:
        # Resolve relative config paths against the workspace root so they work
        # regardless of the process CWD (important for pytest and Docker).
        self.schema_path = str(
            (WORKSPACE_ROOT / schema_path).resolve()
            if not Path(schema_path).is_absolute()
            else Path(schema_path)
        )
        self.rules_path = str(
            (WORKSPACE_ROOT / rules_path).resolve()
            if not Path(rules_path).is_absolute()
            else Path(rules_path)
        )
        self.artifact_store = artifact_store or ArtifactStore()

    def validate(
        self,
        dataset_path: str,
        metadata_path: Optional[str] = None,
        dataset_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_dataset_id = dataset_id or self._dataset_id(dataset_path)
        schema = DatasetLoader.load_json(self.schema_path)
        rules = DatasetLoader.load_json(self.rules_path)
        metadata = DatasetLoader.load_json(metadata_path) if metadata_path else {}
        dataframe = DatasetLoader.load_dataset(dataset_path)

        profile = DatasetProfiler.profile(dataframe)
        validation_results = {
            "schema": SchemaValidator.validate(dataframe, schema),
            "completeness": CompletenessValidator.validate(dataframe),
            "duplicates": DuplicateValidator.validate(dataframe),
            "consistency": ConsistencyValidator.validate(dataframe),
            "metadata": MetadataValidator.validate(metadata, rules["required_metadata"]),
            "provenance": ProvenanceValidator.validate(metadata),
            "integrity": IntegrityBoundaryValidator.validate(dataframe, rules),
        }
        risk_flags = RiskEngine.evaluate(validation_results, rules)
        integrity_score = ScoringEngine.calculate(validation_results, rules)
        classification = ClassificationEngine.classify(integrity_score, rules)
        recommendations = RecommendationEngine.generate(validation_results)

        report = {
            "dataset_id": resolved_dataset_id,
            "state": CertificationState.VALIDATED.value,
            "profile": profile,
            "validation_results": validation_results,
            "risk_flags": risk_flags,
            "integrity_score": integrity_score,
            "classification": classification,
            "recommendations": recommendations,
            "metadata": metadata,
            "audit_trail": [
                {
                    "from_state": CertificationState.NEW.value,
                    "to_state": CertificationState.VALIDATED.value,
                    "rule": "VALIDATION_COMPLETED",
                    "passed": True,
                    "reason": "Dataset package validation completed.",
                }
            ],
        }
        return self.artifact_store.save(resolved_dataset_id, report)

    @staticmethod
    def _dataset_id(dataset_path: str) -> str:
        path = resolve_secure_path(dataset_path)
        digest = hashlib.sha256()
        digest.update(str(path.resolve()).encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
        return digest.hexdigest()[:16]

