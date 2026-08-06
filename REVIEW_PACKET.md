# Review Packet

## Summary

This sprint converges MASTERDB from an isolated backend into an ecosystem
capability: a live MDU client with contract validation/version negotiation
(Phase 1), a MASTERDB <-> TANTRA runtime interface (Phase 2), a Runtime
Discovery API (Phase 3), and Phase 4 hardening (uniform error contract,
structured logging, replay-consistency/audit-completeness endpoints) — on
top of the existing Knowledge Package Lifecycle, Knowledge Object/Provenance
consumption, and Retrieval Readiness services from the prior sprint.

## Implemented — This Sprint (Ecosystem Integration)

- `MDUClient` (`services/mdu_client.py`) — live HTTP client for MDU's
  schema/provenance/canonical/discovery endpoints, configured via
  `MDU_BASE_URL` / `MDU_API_KEY`.
- `MDUContractAdapter` upgraded with `fetch_schema_contract`,
  `fetch_provenance_contract`, `validate_schema_compatibility`, and a
  deterministic `negotiate_version` rule (exact match / minor-version
  drift / major-version mismatch), with permissive placeholder fallback
  when MDU is unreachable.
- `KnowledgeObjectService.lineage()` now consumes MDU's live provenance
  contract (tagged `mdu_provenance`, source `mdu-live` vs `unavailable`)
  alongside MASTERDB's own parent/child walk.
- `TantraInterfaceService` (`services/tantra_interface_service.py`) — the
  single façade TANTRA integrates against: dataset registration, package
  discovery, retrieval-readiness queries, certification-status queries,
  bundled runtime package lookup.
- `RuntimeDiscoveryService` (`services/runtime_discovery_service.py`) +
  `ArtifactStore.list_all()` — deterministic filtered package discovery by
  `package_id`/`dataset_id`/`board`/`medium`/`version`/`status`.
- Phase 4 hardening: uniform `{"error": {...}}` contract via global FastAPI
  exception handlers, structured logging (registration, transitions, MDU
  requests), `PackageRegistryService.audit_completeness()`, and two new
  endpoints — `GET /packages/{id}/replay`, `GET /packages/{id}/audit`.
- 9 new endpoints: `/mdu/status`, `/mdu/schema/{id}`,
  `/mdu/provenance/{id}`, `/mdu/schema-compatibility/{id}`,
  `/tantra/datasets/register`, `/tantra/packages/{id}/retrieval-readiness`,
  `/tantra/certification/{id}`, `/tantra/packages/{id}/runtime`,
  `/discovery/packages`, plus `/packages/{id}/replay` and
  `/packages/{id}/audit` (11 total).
- New tests: `test_mdu_contract_adapter.py`,
  `test_runtime_discovery_service.py`, `test_tantra_interface_service.py`,
  `test_audit_and_replay.py`.
- `MDU_INTERFACE_CONTRACT.md`, `README.md`, `ARCHITECTURE.md`,
  `API_DOCUMENTATION.md`, `HANDOVER.md` all updated for the above.

## Implemented — Prior Sprint (unchanged this round)

- `ValidationService`
- `CertificationService`
- `IngestionDecisionService`
- `ReportService`
- FastAPI REST API
- Auditable certification state machine
- JSON artifact persistence
- Unit tests and API integration tests
- Certified and rejected sample reports

## API Surface

Validation & Certification:

- `POST /validate`
- `POST /certify`
- `GET /status/{dataset_id}`
- `GET /report/{dataset_id}`

MASTERDB Registry (new):

- `POST /packages/register`
- `POST /packages/promote`
- `POST /packages/deprecate`
- `GET /packages/{package_id}`
- `GET /packages/{package_id}/lineage`
- `GET /packages/{package_id}/retrieval`
- `GET /packages/{package_id}/history`
- `POST /packages/{package_id}/knowledge-object` (supporting endpoint, not
  in the original 7 but required to populate lineage for meaningful
  retrieval assessments)
- `GET /packages/{package_id}/replay` (new — Phase 4)
- `GET /packages/{package_id}/audit` (new — Phase 4)

MDU Integration (new — Phase 1):

- `GET /mdu/status`
- `GET /mdu/schema/{dataset_id}`
- `GET /mdu/provenance/{dataset_id}`
- `GET /mdu/schema-compatibility/{dataset_id}?local_schema_version=...`

TANTRA Runtime Interface (new — Phase 2):

- `POST /tantra/datasets/register`
- `GET /tantra/packages/{package_id}/retrieval-readiness`
- `GET /tantra/certification/{dataset_id}`
- `GET /tantra/packages/{package_id}/runtime`

Runtime Discovery (new — Phase 3):

- `GET /discovery/packages` (filterable by `package_id`, `dataset_id`,
  `board`, `medium`, `version`, `status`)

## Certification Rules

Validation always transitions `NEW -> VALIDATED` when checks complete.

Verification transitions `VALIDATED -> VERIFIED` only when:

- Integrity score is at least `75`
- No risk flags exist
- Metadata score is at least `80`
- Provenance score is at least `80`
- Integrity boundary score is at least `80`

Certification transitions `VERIFIED -> CERTIFIED` only when:

- Classification is `Trusted`
- Integrity score is at least `90`
- No risk flags exist
- No recommendations remain

Any failed certification rule transitions to `REJECTED`.

## Knowledge Package Lifecycle Rules

Allowed graph (see `models.PACKAGE_LIFECYCLE_GRAPH`):

`REGISTERED -> INGESTED -> VALIDATED -> VERIFIED -> CERTIFIED ->
RETRIEVAL_READY`, with `DEPRECATED` reachable from any non-terminal state
and `ARCHIVED` reachable only from `DEPRECATED`. `ARCHIVED` is terminal.
Every transition not present in the graph is rejected with a `400` and is
never appended to `history`.

## Retrieval Readiness Rules

- `PACKAGE_CERTIFIED`: lifecycle status is `CERTIFIED` or `RETRIEVAL_READY`.
- `NOT_DEPRECATED_OR_ARCHIVED`: lifecycle status is not `DEPRECATED` or
  `ARCHIVED`.
- `METADATA_COMPLETE`: `board`, `medium`, `language`, `owner`, and
  `schema_version` are all present.
- `LINEAGE_REGISTERED`: a `KnowledgeObject` with a `source_reference` is
  registered for the package.

Status derivation: failing either of the first two rules yields
`NOT_RETRIEVABLE`; failing `METADATA_COMPLETE` or `LINEAGE_REGISTERED`
(while certified and active) yields `PARTIALLY_RETRIEVABLE`; passing all
four while lifecycle status is `CERTIFIED` yields `RETRIEVABLE`; passing all
four while lifecycle status is `RETRIEVAL_READY` yields
`CERTIFIED_RETRIEVABLE`.

## Test Evidence

**This environment has no network access, so `fastapi`/`httpx`/`pydantic`
could not be installed here to execute any test suite.** All new modules
(this sprint and prior) were syntax checked with `python -m py_compile` and
reviewed line-by-line against the existing service's established patterns.
Pure-Python logic that doesn't depend on the missing packages —
`MDUContractAdapter.negotiate_version`'s branching — was additionally
hand-verified by running an isolated copy of the function directly:

```
negotiate_version("2.1", "2.1")  -> compatible=True,  exact_match
negotiate_version("2.1", "2.4")  -> compatible=True,  minor_version_drift
negotiate_version("1.9", "2.0")  -> compatible=False, major_version_mismatch
negotiate_version("1.0", "")     -> compatible=False, unknown
```

Run this in an environment with dependencies installed for real pass/fail
results, including against the live MDU API:

```bash
python -m pip install -r requirements.txt
export MDU_BASE_URL="https://bhiv-mdu-api.onrender.com"
export MDU_API_KEY="<the shared key>"
python -m pytest
uvicorn main:app --reload
# then exercise /mdu/*, /tantra/*, /discovery/packages by hand or via curl
```

Expected test files (prior sprint): `tests/test_package_registry_service.py`,
`tests/test_knowledge_object_service.py`,
`tests/test_retrieval_readiness_service.py`, `tests/test_registry_api.py`.

Expected test files (this sprint): `tests/test_mdu_contract_adapter.py`,
`tests/test_runtime_discovery_service.py`,
`tests/test_tantra_interface_service.py`, `tests/test_audit_and_replay.py`.

## Evidence Not Included (and why)

The task brief asks for runtime screenshots, API screenshots, and
console/log evidence under `/review_packets/`. None of that is included
here, deliberately: producing screenshots of a server that was never
actually started, or console output that was never actually printed, would
be fabricated evidence, not real evidence. Once you run the commands above
in a networked environment, capture that real output and it can be added
here.

## Risk Notes

- Artifact storage is file-based for this handoff, consistent with the
  existing `ArtifactStore` pattern (now reused for registry, knowledge
  object, and retrieval evidence stores under different directories). A
  future platform can replace it without changing service logic.
- `KnowledgeObjectService` currently mirrors a placeholder shape for MDU's
  Knowledge Object contract rather than consuming a finalized one — see
  `MDU_INTERFACE_CONTRACT.md` Known Gaps. This is intentional per the sprint
  brief ("create adapter interfaces with clear placeholders") and should be
  revisited once Nupur publishes the real contract.
- Version compatibility currently checks major-version equality only
  (`schema_version` prefix before the first `.`); this is a placeholder
  rule pending MDU's actual compatibility policy.
- Requests currently pass local paths. Upload handling can be added at the
  API boundary if future ingestion pipelines require multipart packages.
- Existing validators are deterministic but simple; deeper semantic
  validation can be added behind `ValidationService`.
- Test suite could not be executed in this sandbox (no network to install
  dependencies) — see Test Evidence above.
- **The MDU client has never been run against the real MDU service.** Field
  names it expects (`schema_version`/`version`) are a best guess from the
  documented endpoint list, not a confirmed response schema. Verify before
  relying on `/mdu/schema-compatibility/*` in production.
- `KnowledgeObjectService.lineage()`'s `mdu_provenance` field assumes MDU's
  `/provenance` endpoint doubles as the lineage contract, per the
  integration brief's own labeling ("Provenance chain (lineage contract)").
  Confirm with Nupur that no separate lineage endpoint is planned.
- The uniform error contract (`{"error": {...}}`) changes the shape of
  every error response versus the prior `{"detail": ...}` FastAPI default.
  No existing test asserted on that shape, but any external caller that
  parses `detail` directly will need to switch to `error.message`.

## Reviewer Checklist

- Confirm no business logic remains in `main.py`.
- Confirm API responses are JSON-only.
- Confirm certification transitions are auditable.
- Confirm rejected reports include rejection reasons.
- Confirm sample reports cover certified and rejected outcomes.
- Confirm non-goals were not implemented (no embeddings, vector DB, RAG,
  runtime reasoning, or invented canonical schema/ontology semantics).
- Confirm illegal lifecycle transitions are rejected and never recorded.
- Confirm every lifecycle transition records actor, reason, and timestamp.
- Confirm `PackageRegistryService.replay()` detects drift between stored
  status and transition history.
- Confirm retrieval readiness never reports `CERTIFIED_RETRIEVABLE` without
  both `RETRIEVAL_READY` lifecycle status and registered lineage.
- Confirm `KnowledgeObjectService` does not redefine Knowledge Object,
  Provenance, or Lineage semantics beyond the documented placeholder.
- Confirm `MDUClient` never appears anywhere outside
  `services/mdu_client.py` (single seam for MDU's base URL/paths/auth).
- Confirm every MDU-dependent code path degrades to a flagged placeholder
  instead of raising when MDU is unconfigured/unreachable.
- Confirm `TantraInterfaceService` adds no new ownership — every method is
  a direct delegation to an existing service.
- Confirm `/discovery/packages` results are deterministically ordered.
- Confirm the new `{"error": {...}}` contract is acceptable to any existing
  external caller before merging (see Risk Notes).
- Run `python -m pip install -r requirements.txt && python -m pytest` in a
  networked environment before merging, since it could not be run here.
- Run the live MDU verification steps in "Evidence Not Included" above and
  attach real output before considering Phase 5/6 complete.

## Task 4 — Shared Data Services & MASTERDB Convergence

Full detail in `MASTERDB_SHARED_DATA_ARCHITECTURE.md`; evidence in
`review_packets/` (see below). This section summarizes what was delivered
against the six Task 4 phases.

### Implemented

- **Phase 1 — Shared Data Service Registry**: 15 dataset categories
  registered in `shared_data/registry.py`, each declaring purpose, owner,
  consumers, update policy, lifecycle, and dependency map. Read live via
  `GET /shared/registry`.
- **Phase 2 — Shared Service Contracts**: six live services
  (Authentication, Identity, Organizations, Configuration, Knowledge
  References, Notifications), each a thin wrapper over one generic engine
  (`SharedRecordStore`). Contracts served live via `GET /shared/contracts`.
- **Phase 3 — Ecosystem Dependency Mapping**: Product DB → MASTERDB → MDU
  documented in `MASTERDB_SHARED_DATA_ARCHITECTURE.md` §4, including
  ownership, sync model, read/write paths, and what each layer cannot own.
- **Phase 4 — Runtime Integration**: 13 new `/shared/*` endpoints,
  version-aware (`/shared/version-compatibility`), replay-safe
  (`.../replay`), observable (structured logging on every mutation),
  auditable (`.../history`), stateless (JSON-file backed, no in-memory
  session state). No semantic interpretation, ontology, or governance
  logic — `payload` is validated only for required-key presence.
- **Phase 5 — Testing**: 46 new tests across 6 files (96 total, all
  passing) covering cross-service retrieval, version compatibility,
  graceful failures, missing dependency handling, replay consistency, and
  API validation. See `review_packets/runtime/task4_full_test_run.txt`.
- **Phase 6 — Documentation & Handover**: `MASTERDB_SHARED_DATA_ARCHITECTURE.md`
  added; `README.md`, `ARCHITECTURE.md`, `API_DOCUMENTATION.md`,
  `HANDOVER.md`, and this file all updated.

### Evidence included

- `review_packets/runtime/task4_full_test_run.txt` — full verbose pytest
  run (96 passed).
- `review_packets/runtime/task4_live_api_console_log.txt` — structured
  logging output from a live API run (register/update/400/409/404 paths).
- `review_packets/api_responses/*.json` — 23 real request/response pairs
  captured via `TestClient` against the running FastAPI app: every one of
  the 13 `/shared/*` routes exercised, register evidence for all 6 shared
  services, the full register→update→deprecate lifecycle, both outcomes
  of dependency resolution (satisfied and missing), and all failure paths
  (400/404/409).
- `review_packets/architecture_diagram/masterdb_shared_data_architecture.png`
  — rendered diagram of the three-layer model.
- `review_packets/code_packets/changed_files.md`,
  `changed_file_list.txt`, `architecture_delta.md`, and `source/` (literal
  copies of every changed/added file) — full change inventory and
  before/after architecture diff.

### Reviewer checklist — Task 4

- Confirm no dataset in `shared_data/registry.py` duplicates a Product
  Database's private table.
- Confirm `SharedRecordStore` validates only required-*key* presence, never
  payload values — no business logic leaked into the generic engine.
- Confirm `knowledge_references` stores a pointer only; confirm nothing
  under `shared_store/knowledge_references/` ever contains MDU's actual
  schema/provenance content.
- Confirm every `/shared/*` mutation produces a `SharedRecordTransition`
  with actor, reason, timestamp, and version.
- Confirm `.../replay` correctly flags version drift (see
  `test_replay_detects_version_drift`).
- Confirm `.../resolve` reports missing dependencies rather than raising.
- Confirm Task 1–3 routes, services, and tests are unmodified (see
  `review_packets/code_packets/architecture_delta.md` → "What did NOT
  change").


## Constitutional Runtime Activation — current pass

Covers three sequential briefs: BCAES Ecosystem Bootstrap, Production
Convergence & Hardening, and Constitutional Runtime Activation (Phase 1).

**What's live and verified:**
- `/bcaes/*` (17 endpoints) — wired and tested after correcting an
  earlier gap where the module existed but `main.py` never imported it
  (see `BCAES_REGISTRY_ARCHITECTURE.md` §6 for the full correction).
- `/canonical-repository/*` (9 endpoints) — versioned BCAB/BCAES document
  store, placeholder content pending central population.
- `/auth/token`, real JWT-based RBAC enforcement on both modules above.
- Opt-in disk persistence, proven via restart-simulation tests
  (`tests/test_persistence.py`), not just "doesn't crash."
- `/health`, `/ready`, audit logging.
- `CONSTITUTIONAL_RUNTIME_DEFINITION.md` — Phase 1 of the current brief.

**Full suite: 180/180 passing**, 97% coverage across `auth/`,
`bcaes_registry/`, `canonical_repository/` combined. Evidence:
`review_packets/api_responses_bcaes/`,
`api_responses_canonical_repository/`, `runtime_hardening/` — every file
generated by driving a live `TestClient` against the running app
(`scripts/capture_*_evidence.py`), including real 401/403/409 responses
proving the auth/RBAC layer actually rejects unauthorized calls rather
than just accepting everything.

**What's explicitly NOT done** (see `PRODUCTION_HARDENING.md` and
`CONSTITUTIONAL_RUNTIME_DEFINITION.md` §4/§7 for the full lists): real
identity provider behind auth, monitoring/observability, backup/DR,
security/load testing, and live integration with any adjacent service
(MDU/TANTRA/Bucket/InsightFlow/PARIKSHAK/NIYANTRAN/RAJYA/KESHAV/SARATHI/
PRANA/KARMA/BHEX) — none of these have a confirmed reachable contract
from this environment, so none were built against guesses.

### Reviewer checklist — this pass

- Confirm `/bcaes/*` write routes 401 without a token and 403 for an
  actor not in `authority_boundaries` (see
  `tests/test_bcaes_api.py::test_register_without_token_returns_401` /
  `::test_register_with_actor_not_in_authority_boundaries_returns_403`).
- Confirm `/canonical-repository/*` enforces read AND write roles, not
  just write (see `tests/test_canonical_repository_api.py`).
- Confirm persistence is opt-in and default behavior (in-memory) is
  unchanged — `MASTERDB_STORAGE_DIR` unset in every test fixture.
- Confirm `CONSTITUTIONAL_RUNTIME_DEFINITION.md` §4's contract-status
  table matches reality — no adjacent-service integration should exist
  in code that isn't listed there as "live."

## Phase 4 — Runtime Validation (this pass)

Full execution-flow demonstration (Service Discovery → Runtime Request →
MASTERDB → Adjacent Services → Evidence → Replay → Observability) run
against the live app via `scripts/demonstrate_runtime_validation.py`.
Five of six steps fully live and complete; step 3 (Adjacent Services)
honestly partial — no confirmed reachable endpoint for any adjacent
service exists yet, stated plainly rather than simulated. Full writeup:
`review_packets/runtime_validation_phase4/PHASE4_SUMMARY.md`.
