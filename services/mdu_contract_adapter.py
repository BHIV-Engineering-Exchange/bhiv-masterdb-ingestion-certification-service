"""
Adapter interface for the MDU (Nupur) canonical contracts.

MASTERDB does NOT own Knowledge Object, Provenance, Lineage, or schema
contract semantics. Those are owned by MDU. This adapter is the single seam
MASTERDB code depends on for MDU-owned data, in two modes:

  - LIVE mode: an MDUClient is configured (MDU_BASE_URL / MDU_API_KEY) and
    reachable. The adapter fetches real schema/provenance contracts from
    MDU and reports back what MDU actually said — it does not reinterpret
    or "improve" that data.
  - PLACEHOLDER mode: no live MDU connection. The adapter falls back to the
    documented placeholder snapshot below so the rest of MASTERDB keeps
    working, and every response is tagged so callers know it is not
    MDU-confirmed.

Do NOT add new semantics here. If a field or rule is not confirmed by MDU,
mark it as a placeholder and keep the check permissive (log/flag rather than
hard-fail), so MASTERDB never silently invents ontology it doesn't own.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.mdu_client import MDUClient, MDUUnavailableError


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass
class MDUFieldRequirement:
    field_name: str
    required: bool
    confirmed_by_mdu: bool
    note: str = ""


@dataclass
class MDUContractSnapshot:
    """
    Placeholder snapshot of what MASTERDB currently believes about the MDU
    Knowledge Object contract, used only when live MDU is unreachable.
    """

    contract_version: str = "PLACEHOLDER-v0"
    required_fields: List[MDUFieldRequirement] = field(
        default_factory=lambda: [
            MDUFieldRequirement(
                "knowledge_object_id", True, confirmed_by_mdu=False,
                note="Live-checked 2026-07-08 (scripts/confirm_mdu_contract.py, "
                "BHIV-DS-MARITIME-AIS-LIVE-001): does NOT exist as a concept in "
                "MDU's real model. MDU provenance is an append-only event list "
                "(ORIGIN/INGESTION/VALIDATION/...), each with its own event "
                "'id' plus a shared 'dataset_id' -- there is no single "
                "knowledge-object identifier. Needs a design conversation with "
                "Nupur, not just a rename.",
            ),
            MDUFieldRequirement(
                "source_reference", True, confirmed_by_mdu=True,
                note="Confirmed live 2026-07-08 (scripts/confirm_mdu_contract.py, "
                "BHIV-DS-MARITIME-AIS-LIVE-001): present on every provenance "
                "event with this exact field name, as a string (e.g. "
                "'svacs-unified-core/ais_feed'), nullable on some event types.",
            ),
            MDUFieldRequirement(
                "lineage_reference", False, confirmed_by_mdu=False,
                note="Live-checked 2026-07-08 (scripts/confirm_mdu_contract.py, "
                "BHIV-DS-MARITIME-AIS-LIVE-001): does NOT exist as a field. "
                "MDU's lineage is the ordered event list itself, not a pointer "
                "field on a record. Needs a design conversation with Nupur on "
                "how MASTERDB should reference/consume that list.",
            ),
            MDUFieldRequirement(
                "derivation_path", False, confirmed_by_mdu=False,
                note="Live-checked 2026-07-08 (scripts/confirm_mdu_contract.py, "
                "BHIV-DS-MARITIME-AIS-LIVE-001): does NOT exist as a field. "
                "Closest real analog is 'transformation_reference' (null on "
                "every observed event so far) plus event ordering. Needs "
                "confirmation from Nupur before MASTERDB relies on either.",
            ),
        ]
    )


def _major_minor(version: str) -> tuple:
    """
    Best-effort semantic-version split. Never raises: a version string that
    doesn't parse cleanly degrades to (raw_string, "0") so negotiation can
    still report an explicit mismatch instead of crashing the caller.
    """
    parts = version.split(".")
    major = parts[0] if parts else version
    minor = parts[1] if len(parts) > 1 else "0"
    return major, minor


class MDUContractAdapter:
    """
    Consumption boundary for MDU-owned definitions.

    Callers must not assume placeholder-mode responses are authoritative —
    check `source` on returned dicts ("mdu-live" vs "placeholder") if that
    distinction matters to the caller.
    """

    def __init__(
        self,
        snapshot: Optional[MDUContractSnapshot] = None,
        client: Optional[MDUClient] = None,
    ) -> None:
        self.snapshot = snapshot or MDUContractSnapshot()
        self.client = client or MDUClient()
        # canonical_id -> MDU internal UUID. Confirmed live:
        # /schemas/dataset/{id} and /datasets/{id}/provenance require MDU's
        # internal UUID, while MASTERDB's registry only knows the canonical
        # string ID (e.g. "BHIV-DS-MARITIME-AIS-LIVE-001"). The canonical
        # dataset endpoint accepts the string ID and returns the UUID, so we
        # resolve through that once per process and cache the result.
        self._id_resolution_cache: Dict[str, str] = {}

    def _resolve_mdu_id(self, dataset_id: str, trace_id: Optional[str] = None) -> str:
        """
        Resolve a MASTERDB dataset_id (canonical string or already a UUID)
        to the internal UUID MDU's schema/provenance endpoints require.

        Raises MDUUnavailableError if resolution fails — callers already
        handle that the same way they handle any other MDU-unreachable
        case, so no new error handling is needed upstream.
        """
        if _UUID_RE.match(dataset_id):
            return dataset_id
        if dataset_id in self._id_resolution_cache:
            return self._id_resolution_cache[dataset_id]

        canonical = self.client.get_canonical_dataset(dataset_id, trace_id=trace_id)
        resolved = canonical.get("id")
        if not resolved:
            raise MDUUnavailableError(
                f"MDU canonical dataset lookup for '{dataset_id}' did not "
                "return an 'id' field to resolve against schema/provenance "
                "endpoints."
            )
        self._id_resolution_cache[dataset_id] = resolved
        return resolved

    # -- placeholder-mode surface (unchanged behavior) -----------------------

    def is_contract_finalized(self) -> bool:
        return all(f.confirmed_by_mdu for f in self.snapshot.required_fields)

    def required_field_names(self) -> List[str]:
        return [f.field_name for f in self.snapshot.required_fields if f.required]

    def known_gaps(self) -> List[str]:
        return [
            f"{f.field_name}: {f.note}"
            for f in self.snapshot.required_fields
            if not f.confirmed_by_mdu
        ]

    # -- Phase 1: live contract consumption -----------------------------------

    def is_live(self) -> bool:
        return self.client.is_configured()

    def fetch_schema_contract(self, dataset_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch MDU's canonical (current) schema for a dataset. Raises
        MDUUnavailableError if MDU is unconfigured/unreachable — callers
        decide whether that's fatal for their operation; this adapter never
        fabricates a schema.

        Accepts either MASTERDB's canonical string dataset_id or MDU's
        internal UUID; resolves the former to the latter internally, since
        MDU's schema endpoint only accepts its own UUID.

        MDU returns a LIST of schema version records (schema history), not
        a single object. This method returns only the current (index 0)
        version.
        """
        resolved_id = self._resolve_mdu_id(dataset_id, trace_id=trace_id)
        schema = self.client.get_dataset_schema(resolved_id, trace_id=trace_id)
        if isinstance(schema, list):
            schema = schema[0] if schema else {}
        return schema

    def fetch_provenance_contract(self, dataset_id: str, trace_id: Optional[str] = None) -> Any:
        """
        Fetch MDU's provenance/lineage chain for a dataset, verbatim.

        Accepts either MASTERDB's canonical string dataset_id or MDU's
        internal UUID; resolves the former to the latter internally, since
        MDU's provenance endpoint only accepts its own UUID.
        """
        resolved_id = self._resolve_mdu_id(dataset_id, trace_id=trace_id)
        return self.client.get_dataset_provenance(resolved_id, trace_id=trace_id)

    def fetch_dataset_relationships(self, dataset_id: str, trace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch lineage relationships involving a dataset from MDU.
        """
        resolved_id = self._resolve_mdu_id(dataset_id, trace_id=trace_id)
        relationships = self.client.get_dataset_relationships(resolved_id, trace_id=trace_id)
        return relationships if isinstance(relationships, list) else []

    def fetch_canonical_dataset(self, dataset_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        return self.client.get_canonical_dataset(dataset_id, trace_id=trace_id)

    # -- Provenance and Lineage Mutation --------------------------------------

    def record_provenance_event(
        self,
        dataset_id: str,
        event_type: str,
        recorded_by: str = "MASTERDB",
        source_system: str = "MASTERDB",
        source_reference: Optional[str] = None,
        ingestion_pipeline: Optional[str] = None,
        transformation_reference: Optional[str] = None,
        trust_at_event: Optional[str] = None,
        notes: Optional[str] = None,
        is_replay_safe: bool = True,
        replay_context: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submit a new provenance event for a dataset to MDU.
        Resolves canonical dataset_id to MDU internal UUID automatically.
        """
        resolved_id = self._resolve_mdu_id(dataset_id, trace_id=trace_id)
        payload: Dict[str, Any] = {
            "event_type": event_type,
            "recorded_by": recorded_by,
            "source_system": source_system,
            "is_replay_safe": is_replay_safe,
        }
        if source_reference is not None:
            payload["source_reference"] = source_reference
        if ingestion_pipeline is not None:
            payload["ingestion_pipeline"] = ingestion_pipeline
        if transformation_reference is not None:
            payload["transformation_reference"] = transformation_reference
        if trust_at_event is not None:
            payload["trust_at_event"] = trust_at_event
        if notes is not None:
            payload["notes"] = notes
        if replay_context is not None:
            payload["replay_context"] = replay_context

        return self.client.record_provenance(resolved_id, payload, trace_id=trace_id)

    def create_dataset_relationship(
        self,
        parent_dataset_id: str,
        child_dataset_id: str,
        relationship_type: str = "DERIVED_FROM",
        created_by: str = "MASTERDB",
        description: Optional[str] = None,
        transformation_notes: Optional[str] = None,
        chain_replay_safe: bool = True,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a lineage relationship edge between parent and child datasets in MDU.
        Resolves canonical dataset IDs to MDU internal UUIDs automatically.
        """
        parent_uuid = self._resolve_mdu_id(parent_dataset_id, trace_id=trace_id)
        child_uuid = self._resolve_mdu_id(child_dataset_id, trace_id=trace_id)

        payload: Dict[str, Any] = {
            "parent_dataset_id": parent_uuid,
            "child_dataset_id": child_uuid,
            "relationship_type": relationship_type,
            "created_by": created_by,
            "chain_replay_safe": chain_replay_safe,
        }
        if description is not None:
            payload["description"] = description
        if transformation_notes is not None:
            payload["transformation_notes"] = transformation_notes

        return self.client.create_relationship(payload, trace_id=trace_id)

    # -- Schema negotiation ---------------------------------------------------

    def validate_schema_compatibility(
        self, dataset_id: str, local_schema_version: str, trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Compare MASTERDB's locally-declared schema_version for a package
        against MDU's canonical schema for that dataset_id.

        Falls back to placeholder-mode (major-version-only, unconfirmed) if
        live MDU is unreachable, so package registration never hard-fails
        purely because MDU is down — it degrades to a flagged gap instead.
        """
        if not self.client.is_configured():
            return {
                "source": "placeholder",
                "compatible": True,
                "reason": "MDU not configured; falling back to permissive "
                "placeholder check (no hard-fail on unconfirmed contract).",
                "known_gaps": self.known_gaps(),
            }
        try:
            resolved_id = self._resolve_mdu_id(dataset_id, trace_id=trace_id)
            schema = self.client.get_dataset_schema(resolved_id, trace_id=trace_id)
        except MDUUnavailableError as exc:
            return {
                "source": "placeholder",
                "compatible": True,
                "reason": f"MDU unreachable ({exc}); falling back to permissive "
                "placeholder check.",
                "known_gaps": self.known_gaps(),
            }

        if isinstance(schema, list):
            schema = schema[0] if schema else {}

        mdu_schema_version = str(
            schema.get("schema_version") or schema.get("version") or ""
        )
        negotiation = self.negotiate_version(local_schema_version, mdu_schema_version)
        return {
            "source": "mdu-live",
            "dataset_id": dataset_id,
            "mdu_schema_version": mdu_schema_version,
            "local_schema_version": local_schema_version,
            **negotiation,
        }

    @staticmethod
    def negotiate_version(local_version: str, remote_version: str) -> Dict[str, Any]:
        """
        Deterministic, MASTERDB-side version-negotiation rule:
          - equal strings              -> compatible, exact match
          - equal major, differing minor -> compatible, with a warning
          - differing major             -> incompatible
        """
        if not remote_version:
            return {
                "compatible": False,
                "negotiation": "unknown",
                "reason": "MDU did not report a schema_version for this dataset.",
            }
        if local_version == remote_version:
            return {"compatible": True, "negotiation": "exact_match", "reason": ""}

        local_major, _ = _major_minor(local_version)
        remote_major, _ = _major_minor(remote_version)
        if local_major == remote_major:
            return {
                "compatible": True,
                "negotiation": "minor_version_drift",
                "reason": f"Major version {local_major} matches; minor versions "
                f"differ ({local_version} vs {remote_version}).",
            }
        return {
            "compatible": False,
            "negotiation": "major_version_mismatch",
            "reason": f"Major version mismatch: local={local_version} "
            f"mdu={remote_version}.",
        }