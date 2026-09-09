# API Documentation

Base URL for local development:

```text
http://127.0.0.1:8000
```

All endpoints return structured JSON only.

> The BCAES Canonical Registry's `/bcaes/*` endpoints (registry CRUD,
> search, relationships, validation, production convergence, reality
> snapshot) are documented separately in `BCAES_REGISTRY_ARCHITECTURE.md`
> §6, since they're a distinct, additive module rather than part of the
> certification/lifecycle/lineage API below.

> The Database Targets endpoints (`GET /databases`, `GET /databases/{key}`,
> `POST /ingest`, `GET /ingest/jobs*`) — the controlled attachment of this
> certification pipeline to the 8 MASTERDB target databases for the
> Dashboard & Control Center — are documented in
> `DATABASE_TARGETS_ARCHITECTURE.md`, including the RBAC role per database
> and the full RBAC -> format -> certification-gate -> routed control
> chain.

## POST /validate

Runs deterministic validation checks and stores a validation report.

Request:

```json
{
  "dataset_id": "sample-certified",
  "dataset_path": "datasets/certifiable_sample.csv",
  "metadata_path": "datasets/metadata.json"
}
```

Response:

```json
{
  "dataset_id": "sample-certified",
  "state": "VALIDATED",
  "report": {
    "dataset_id": "sample-certified",
    "state": "VALIDATED",
    "integrity_score": 100.0,
    "classification": "Trusted",
    "risk_flags": []
  }
}
```

## POST /certify

Runs certification against an existing report. If `dataset_id` is unknown, callers may include `dataset_path` and `metadata_path` to validate and certify in one call.

Request using an existing report:

```json
{
  "dataset_id": "sample-certified"
}
```

Request using a dataset package:

```json
{
  "dataset_id": "sample-certified",
  "dataset_path": "datasets/certifiable_sample.csv",
  "metadata_path": "datasets/metadata.json"
}
```

Response:

```json
{
  "dataset_id": "sample-certified",
  "state": "CERTIFIED",
  "decision": {
    "dataset_id": "sample-certified",
    "eligible_for_masterdb": true,
    "state": "CERTIFIED",
    "classification": "Trusted",
    "integrity_score": 100.0,
    "rejection_reasons": [],
    "audit_trail": []
  },
  "report": {}
}
```

## GET /status/{dataset_id}

Returns compact ingestion status for dashboards, registries, and orchestration services.

Response:

```json
{
  "dataset_id": "sample-certified",
  "state": "CERTIFIED",
  "classification": "Trusted",
  "integrity_score": 100.0,
  "eligible_for_masterdb": true
}
```

## GET /report/{dataset_id}

Returns the full persisted validation and certification artifact.

Response includes:

- Dataset profile
- Validation results
- Risk flags
- Integrity score
- Classification
- Recommendations
- Ingestion decision
- Audit trail

## Error Responses

Unknown dataset:

```json
{
  "detail": "No report found for dataset_id=unknown"
}
```

Invalid request or unreadable dataset package:

```json
{
  "detail": "error details"
}
```

---

# MASTERDB Registry API (Phase 4)

Knowledge Package Lifecycle, Provenance/Lineage, and Retrieval Readiness
endpoints. These are additive to the validation/certification endpoints
above and operate on `KnowledgePackage` records rather than raw dataset
reports.

## POST /packages/register

Registers a new `KnowledgePackage` in status `REGISTERED`.

Request:

```json
{
  "dataset_id": "sample-certified",
  "dataset_version": "1.0.0",
  "schema_version": "2",
  "board": "AI",
  "medium": "text",
  "language": "en",
  "owner": "kavy",
  "actor": "pipeline",
  "reason": "Initial package registration."
}
```

Response: the full `KnowledgePackage`, including `package_id` and a
one-entry `history` recording the `REGISTERED` transition.

## POST /packages/promote


Moves a package to the next lifecycle status. Rejects any edge not present
in the lifecycle graph (see `ARCHITECTURE.md`) with `400`.

Request:

```json
{
  "package_id": "pkg-...",
  "to_status": "INGESTED",
  "actor": "pipeline",
  "reason": "Ingestion pipeline completed."
}
```

Response: the updated `KnowledgePackage` with the new transition appended
to `history`.

## POST /packages/deprecate

Convenience endpoint that always transitions to `DEPRECATED`, valid from any
non-terminal, non-deprecated status.

Request:

```json
{
  "package_id": "pkg-...",
  "actor": "owner",
  "reason": "Superseded by a newer dataset version."
}
```

## GET /packages/{package_id}

Returns the current `KnowledgePackage` record, including its full `history`.

## GET /packages/{package_id}/history

Returns just the transition history:

```json
{
  "package_id": "pkg-...",
  "history": [
    {
      "transition_id": "txn-...",
      "from_status": null,
      "to_status": "REGISTERED",
      "reason": "Initial package registration.",
      "actor": "pipeline",
      "timestamp": "2026-07-06T00:00:00+00:00"
    }
  ]
}
```

## POST /packages/{package_id}/knowledge-object

Registers a `KnowledgeObject` (provenance/lineage pointer) for a package.
Not one of the seven endpoints named in the sprint spec, but required to
exercise `/lineage` and `/retrieval` meaningfully — it is the write side of
the Knowledge Object & Provenance Engine. `package_id` in the path and body
must match.

Request:

```json
{
  "package_id": "pkg-...",
  "parent_package": null,
  "source_reference": "s3://bucket/source.csv",
  "lineage_reference": null,
  "derivation_path": ["ingest", "clean"]
}
```

`400` if `parent_package` is set but does not exist, or if schema versions
are major-version incompatible with the declared parent.

## GET /packages/{package_id}/lineage

Returns ancestor chain and declared descendants for a package's Knowledge
Object, plus any `known_gaps` in the current MDU contract placeholder.

```json
{
  "package_id": "pkg-...",
  "knowledge_object_registered": true,
  "knowledge_object_id": "kobj-...",
  "knowledge_hash": "…",
  "source_reference": "s3://bucket/source.csv",
  "lineage_reference": null,
  "derivation_path": ["ingest", "clean"],
  "ancestors": [],
  "descendants": [],
  "known_gaps": ["source_reference: Placeholder: assumed to be a URI/path string..."]
}
```

## GET /packages/{package_id}/retrieval

Runs the Retrieval Readiness Engine and returns a `RetrievalEvidence`
artifact. Certification alone does not imply retrievability; see
`ARCHITECTURE.md` for the rule set.

```json
{
  "package_id": "pkg-...",
  "status": "PARTIALLY_RETRIEVABLE",
  "rules": [
    {"rule": "PACKAGE_CERTIFIED", "passed": true, "detail": "Package status is CERTIFIED."},
    {"rule": "NOT_DEPRECATED_OR_ARCHIVED", "passed": true, "detail": "Package is active."},
    {"rule": "METADATA_COMPLETE", "passed": true, "detail": "All required package metadata fields are present."},
    {"rule": "LINEAGE_REGISTERED", "passed": false, "detail": "No knowledge object with a source_reference is registered for this package."}
  ],
  "corrective_actions": [
    "Register a Knowledge Object with a source_reference for this package via the Knowledge Object & Provenance Engine."
  ],
  "generated_at": "2026-07-06T00:00:00+00:00"
}
```

## Uniform Error Contract (Phase 4)

Every error response — validation failure, missing entity, invalid lifecycle
transition, upstream MDU failure, or unhandled exception — is shaped the
same way, so any consumer (TANTRA included) can parse errors generically:

```json
{
  "error": {
    "type": "http_error",
    "message": "No package found for package_id=unknown",
    "path": "/packages/unknown"
  }
}
```

`type` is one of: `http_error` (expected 4xx conditions — not found, invalid
transition, upstream MDU failure surfaced as 502) or `internal_error` (an
unhandled 500; logged server-side with a stack trace, never leaked to the
caller).

Unknown package:

```json
{"error": {"type": "http_error", "message": "No package found for package_id=unknown", "path": "/packages/unknown"}}
```

Illegal lifecycle transition:

```json
{"error": {"type": "http_error", "message": "Cannot transition package pkg-... from REGISTERED to CERTIFIED. Allowed transitions from REGISTERED: ['INGESTED', 'DEPRECATED'].", "path": "/packages/promote"}}
```

## GET /packages/{package_id}/replay (Phase 4)

Recomputes lifecycle status purely by walking the recorded transition
history and validates every hop against the lifecycle graph, independent of
the stored `status` field. Used to detect drift/corruption.

```json
{"package_id": "pkg-...", "replay_consistent": true, "replayed_status": "CERTIFIED"}
```

## GET /packages/{package_id}/audit (Phase 4)

Audit-completeness report: checks the transition history has exactly one
root transition, every transition has a non-empty actor/reason/timestamp,
timestamps are monotonic, and folds in the replay-consistency result.

```json
{
  "package_id": "pkg-...",
  "complete": true,
  "issues": [],
  "replay_consistent": true,
  "replay_error": null,
  "transition_count": 3
}
```

---

# Phase 1 — MDU Integration Endpoints

MASTERDB does not own schema/provenance/lineage semantics. These endpoints
expose what MDU reports, plus MASTERDB's own version-negotiation decision
on top of it. Configure `MDU_BASE_URL` / `MDU_API_KEY` as environment
variables to enable live mode; without them every call below degrades to a
flagged placeholder rather than failing.
  
## GET /mdu/status

```json
{"live": true, "contract_finalized": false, "known_gaps": ["knowledge_object_id: ...", "..."]}
```

## GET /mdu/schema/{dataset_id}

Passes through MDU's `GET /api/v1/schemas/dataset/{dataset_id}` response
verbatim. Returns `502` with the uniform error contract if MDU is
unreachable.

## GET /mdu/provenance/{dataset_id}

Passes through MDU's `GET /api/v1/datasets/{dataset_id}/provenance`
response verbatim (this is MDU's documented lineage contract).

## GET /mdu/schema-compatibility/{dataset_id}?local_schema_version=1.0

Compares a locally-declared `schema_version` against MDU's canonical
schema for the dataset, using MASTERDB's own negotiation rule (exact match
/ minor-version drift / major-version mismatch):

```json
{
  "source": "mdu-live",
  "dataset_id": "BHIV-DS-MARITIME-AIS-LIVE-001",
  "mdu_schema_version": "2.1",
  "local_schema_version": "2.1",
  "compatible": true,
  "negotiation": "exact_match",
  "reason": ""
}
```

If MDU is unreachable/unconfigured:

```json
{
  "source": "placeholder",
  "compatible": true,
  "reason": "MDU not configured; falling back to permissive placeholder check (no hard-fail on unconfirmed contract).",
  "known_gaps": ["..."]
}
```

---

# Phase 2 — MASTERDB <-> TANTRA Runtime Interface

The single surface TANTRA integrates against. All endpoints are read-mostly
façades over MASTERDB's existing registry/lineage/retrieval services — no
new ownership is introduced here.

## POST /tantra/datasets/register

Request/response identical to `POST /packages/register` (see above); this
is the TANTRA-facing alias of the same operation, recorded with
`actor="tantra"` by default.

## GET /tantra/packages/{package_id}/retrieval-readiness

Identical response shape to `GET /packages/{package_id}/retrieval`.

## GET /tantra/certification/{dataset_id}

```json
{
  "dataset_id": "sample-certified",
  "state": "CERTIFIED",
  "classification": "Trusted",
  "integrity_score": 100.0,
  "eligible_for_masterdb": true
}
```

`404` (uniform error contract) if no certification report exists for that
`dataset_id`.

## GET /tantra/packages/{package_id}/runtime

The bundled runtime-lookup view: lifecycle state, lineage, retrieval
readiness, and certification status (best-effort, by `dataset_id`) in one
call.

```json
{
  "package": {"package_id": "pkg-...", "dataset_id": "ds-1", "status": "CERTIFIED", "...": "..."},
  "lineage": {"package_id": "pkg-...", "knowledge_object_registered": true, "...": "...", "mdu_provenance": {"source": "mdu-live", "dataset_id": "ds-1", "provenance": {"...": "..."}}},
  "retrieval_readiness": {"package_id": "pkg-...", "status": "RETRIEVABLE", "rules": ["..."]},
  "certification_status": {"dataset_id": "ds-1", "state": "CERTIFIED", "...": "..."}
}
```

---

# Phase 3 — Runtime Discovery API

## GET /discovery/packages

Deterministic filtered lookup shared by TANTRA and any other downstream
consumer — no ranking or relevance scoring, results always sorted by
`package_id` so identical queries against identical state return identical
order.

Query parameters (all optional, combinable): `package_id`, `dataset_id`,
`board`, `medium`, `version` (matches either `dataset_version` or
`schema_version`), `status` (one of the `PackageStatus` enum values).

```
GET /discovery/packages?board=maritime&status=CERTIFIED
```

```json
{
  "count": 2,
  "packages": [
    {"package_id": "pkg-aaa...", "dataset_id": "ds-1", "board": "maritime", "status": "CERTIFIED", "...": "..."},
    {"package_id": "pkg-bbb...", "dataset_id": "ds-2", "board": "maritime", "status": "CERTIFIED", "...": "..."}
  ]
}
```

## Task 4 — Shared Data Services & MASTERDB Convergence

Full design in `MASTERDB_SHARED_DATA_ARCHITECTURE.md`. `{service_name}` is
one of: `authentication`, `identity`, `organizations`, `configuration`,
`knowledge-references`, `notifications`.

### `GET /shared/registry`

Lists all 15 canonical shared dataset definitions.

```json
{"count": 15, "datasets": [{"name": "identity", "purpose": "...", "owner": "MASTERDB", "consumers": ["TANTRA", "UniGuru", "..."], "update_policy": "...", "lifecycle": "...", "dependency_map": [], "implemented": true, "service_endpoint": "/shared/identity"}]}
```

### `GET /shared/registry/{dataset_name}`

Single dataset definition. `404` if `dataset_name` is unknown.

### `GET /shared/contracts` / `GET /shared/contracts/{service_name}`

Machine-readable service contract (version, inputs, outputs, dependencies,
failure behaviour, ownership boundary) for all six or one shared service.

### `GET /shared/version-compatibility?local_version=&remote_version=`

Generic major/minor version-negotiation check, reused across all shared
services.

```json
{"compatible": true, "negotiation": "minor_version_drift", "reason": "Major version 1 matches; minor versions differ (1.2 vs 1.5)."}
```

### `POST /shared/{service_name}/register`

```json
{"record_id": "id-1", "payload": {"display_name": "Kavy"}, "actor": "kavy", "reason": "initial identity record"}
```

Returns the created `SharedRecord` (version 1). `400` if a required payload
field is missing (per-service required fields are in
`services/shared_platform_services.py` and `GET /shared/contracts`). `409`
if `record_id` already exists.

### `PUT /shared/{service_name}/{record_id}`

```json
{"payload": {"display_name": "Kavy S"}, "actor": "kavy", "reason": "name update"}
```

Increments `version` and appends an `UPDATED` transition. `404` if unknown,
`400` if the record is deprecated or the payload is invalid.

### `POST /shared/{service_name}/{record_id}/deprecate`

```json
{"actor": "kavy", "reason": "retired"}
```

Marks the record deprecated (terminal — further updates return `400`).

### `GET /shared/{service_name}`

Lists every record for that service.

### `GET /shared/{service_name}/{record_id}`

Fetches a single record. `404` if unknown.

### `GET /shared/{service_name}/{record_id}/history`

Full ordered transition trail (`REGISTERED` / `UPDATED` / `DEPRECATED`,
each with `actor`, `reason`, `timestamp`, `version`).

### `GET /shared/{service_name}/{record_id}/replay`

Rebuilds version/deprecated state purely from stored history for drift
detection.

```json
{"record_id": "cfg-1", "replay_consistent": true, "replayed_version": 2, "replayed_deprecated": false, "stored_version": 2, "stored_deprecated": false}
```

### `GET /shared/{service_name}/{record_id}/resolve`

Cross-service dependency resolution (e.g. an `organizations` record's
`owner_identity_id` resolved against the `identity` service). Never
hard-fails on a missing dependency — it is reported instead.

```json
{"service": "organizations", "record": {"...": "..."}, "resolved_dependencies": {"owner_identity_id": {"...": "..."}}, "missing_dependencies": [], "fully_resolved": true}
```


