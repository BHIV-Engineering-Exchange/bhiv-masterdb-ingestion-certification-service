# Handover

## Owner Role

MASTERDB Core Knowledge Platform Engineer — ingestion readiness, Knowledge
Package Lifecycle, Provenance/Lineage consumption, Retrieval Readiness, and
(this sprint) MASTERDB's runtime integration surface with MDU and TANTRA
for the BHIV ecosystem.

## What This Service Does

This service validates dataset packages, certifies ingestion eligibility,
owns the Knowledge Package Lifecycle (Dataset Registry), Knowledge
Object/Provenance consumption, and Retrieval Readiness/Evidence, and now
exposes those capabilities as ecosystem-reachable surfaces: a live MDU
client with schema/provenance consumption and version negotiation, a
MASTERDB <-> TANTRA runtime interface, and a Runtime Discovery API. All
output is deterministic and replayable through persisted JSON records —
validation/certification reports, package lifecycle history, knowledge
object/lineage records, and retrieval evidence.

**Status of this sprint's work**: code-complete for Phases 1–3 (MDU live
client, TANTRA interface, Runtime Discovery) plus Phase 4 hardening (error
contract, logging, replay/audit endpoints). **Not yet run against the real
MDU service or executed as a test suite** — this was built in a sandbox
with no outbound network access and none of `fastapi`/`httpx`/`pydantic`
installed. Treat this as a reviewed, syntax-checked patch that still needs
one real test-and-verify pass before merge. See "Before You Merge" below.

## How To Run

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the API:

```bash
uvicorn main:app --reload
```

Run tests:

```bash
python -m pytest
```

## Integration Contract

Future ingestion pipelines should call:

1. `POST /validate`
2. `POST /certify`
3. `GET /status/{dataset_id}` or `GET /report/{dataset_id}`

The only accepted ingestion decision is:

```json
{
  "eligible_for_masterdb": true,
  "state": "CERTIFIED"
}
```

Any other state must be treated as not eligible for MASTERDB ingestion.

Once a dataset is certified, register it as a `KnowledgePackage` and drive it
through the lifecycle:

1. `POST /packages/register`
2. `POST /packages/promote` (repeat through `INGESTED -> VALIDATED ->
   VERIFIED -> CERTIFIED -> RETRIEVAL_READY`)
3. `POST /packages/{package_id}/knowledge-object` to attach lineage
4. `GET /packages/{package_id}/lineage` and
   `GET /packages/{package_id}/retrieval` to check readiness before any
   downstream system treats the package as retrievable

Only `CERTIFIED_RETRIEVABLE` (or `RETRIEVABLE`, with awareness that lineage
metadata is present but the package hasn't been marked `RETRIEVAL_READY`
yet) should be treated as safe to retrieve from. `NOT_RETRIEVABLE` and
`PARTIALLY_RETRIEVABLE` must not be surfaced to retrieval consumers.

## Before You Merge

1. `pip install -r requirements.txt && pytest` in a networked environment.
   None of the tests in this sprint's diff (`test_mdu_contract_adapter.py`,
   `test_runtime_discovery_service.py`, `test_tantra_interface_service.py`,
   `test_audit_and_replay.py`) have been executed yet.
2. Set `MDU_BASE_URL` / `MDU_API_KEY` and hit `GET /mdu/schema/<a real
   dataset_id>` and `GET /mdu/provenance/<a real dataset_id>` against the
   live service. Confirm the actual field names MDU returns — in
   particular whether the schema payload uses `schema_version` or
   `version` — and adjust the two `.get(...)` lookups in
   `MDUContractAdapter.validate_schema_compatibility` if they don't match.
3. Confirm with Nupur whether the `/provenance` endpoint really is the full
   lineage contract (assumed here per the integration brief) or whether a
   separate lineage endpoint is planned.
4. Capture real screenshots/console output for the review packet once 1–3
   are done — none are included yet; see `REVIEW_PACKET.md`.

## Files To Know

- `main.py`: REST entrypoint only.
- `services/validation_service.py`: Validation orchestration.
- `services/certification_service.py`: State transition rules.
- `services/report_service.py`: Status and report lookup.
- `services/artifact_store.py`: File-based report persistence.
- `services/package_registry_service.py`: Dataset Registry / Knowledge
  Package Lifecycle Manager. Owns `PACKAGE_LIFECYCLE_GRAPH`, transition
  validation, history, and replay.
- `services/knowledge_object_service.py`: Knowledge Object & Provenance
  Engine. Consumes MDU semantics through `MDUContractAdapter`; validates
  parent/child relationships and major-version schema compatibility.
- `services/mdu_contract_adapter.py`: Consumption boundary for MDU's
  contract. Live mode (via `MDUClient`) when `MDU_BASE_URL`/`MDU_API_KEY`
  are set; permissive placeholder fallback otherwise. Update this file,
  not the service logic, once MDU's semantics are confirmed.
- `services/mdu_client.py`: The only module that knows MDU's base URL,
  auth header, and endpoint paths. Pure transport — no interpretation.
- `services/retrieval_readiness_service.py`: Retrieval Readiness & Evidence
  Service. Produces replayable `RetrievalEvidence`.
- `services/tantra_interface_service.py`: MASTERDB <-> TANTRA runtime
  interface façade (dataset registration, package discovery, retrieval
  readiness, certification status, bundled runtime package lookup).
- `services/runtime_discovery_service.py`: Deterministic filtered package
  lookup (Phase 3), backed by `ArtifactStore.list_all()`.
- `config/validation_rules.json`: Scoring and threshold rules.
- `config/schema.json`: Dataset schema expectations.
- `MDU_INTERFACE_CONTRACT.md`: Consumed contracts, live transport
  configuration, required fields, version compatibility rules, known gaps,
  and future extension points for the MASTERDB <-> MDU integration.

## Sample Artifacts

- `reports/sample-certified.json`
- `reports/sample-rejected.json`
- `registry_store/`, `knowledge_object_store/`, `retrieval_evidence_store/`
  are created on first use and hold package, lineage, and retrieval
  evidence records respectively (git-ignored sample data is not checked in;
  run the test suite or the example `curl` calls in `README.md` to
  populate them locally).

## Extension Points

- Replace `ArtifactStore` with platform storage (applies to all four
  stores: reports, registry, knowledge objects, retrieval evidence).
- Add upload endpoints while keeping `ValidationService` unchanged.
- Add new validators under `validators/` and include them in `ValidationService`.
- Adjust thresholds in `config/validation_rules.json`.
- Once MDU finalizes its contract, update `MDUContractAdapter` and
  `MDU_INTERFACE_CONTRACT.md` together; `KnowledgeObjectService` should not
  need structural changes if the adapter seam is respected.
- Runtime Discovery is now implemented (`GET /discovery/packages`,
  `RuntimeDiscoveryService`). If TANTRA needs ranking/relevance on top of
  the deterministic filter, that belongs in TANTRA, not here.

## Non-Goals

Do not add vector search, RAG, embeddings, runtime reasoning, canonical
schema/ontology definitions, or UI logic to this service. Registry and
Knowledge Package Lifecycle are now in-scope (this sprint); do not
duplicate MDU's ownership of Knowledge Object/Provenance/Lineage
*semantics* — MASTERDB only consumes them through the adapter boundary.

## Task 4 — Shared Data Services & MASTERDB Convergence

Added a shared operational data platform layer (`/shared/*`) — full design
in `MASTERDB_SHARED_DATA_ARCHITECTURE.md`. Summary for handover:

- **New modules**: `shared_data/registry.py` (15 dataset definitions),
  `services/shared_data_registry_service.py`,
  `services/shared_record_store.py` (generic engine),
  `services/shared_platform_services.py` (six service contracts),
  `services/shared_dependency_resolver.py`,
  `services/shared_version_compatibility.py`.
- **New storage**: `shared_store/{authentication,identity,organizations,
  configuration,knowledge_references,notifications}/`, created on first
  use, same JSON-per-record pattern as `registry_store/`.
- **New tests**: `tests/test_shared_record_store.py`,
  `tests/test_shared_platform_services.py`,
  `tests/test_shared_data_registry.py`,
  `tests/test_shared_dependency_resolver.py`,
  `tests/test_shared_version_compatibility.py`, `tests/test_shared_api.py`
  (46 tests; 96 total in the suite, all passing).
- **Nothing from Task 1–3 was modified** beyond the two-line version bump
  in `main.py` (`1.2.0` → `1.3.0`) and new imports/route registrations
  appended at the end of `main.py` — certification, lifecycle, lineage,
  retrieval, MDU adapter, and TANTRA/discovery code is untouched.
- **Extension point**: to bring one of the 9 registered-but-not-yet-built
  datasets (e.g. `roles`, `feature_flags`) online, add one
  `SharedRecordStore` subclass in `shared_platform_services.py`, register
  it in `build_shared_service_registry()`, add a `SERVICE_CONTRACTS`
  entry, and flip `implemented: True` + `service_endpoint` in
  `shared_data/registry.py`. No changes to `main.py`'s routes are needed —
  they are already generic over `{service_name}`.
- **Open item for Nupur**: `knowledge_references` currently declares its
  MDU dependency informationally only (`DEPENDENCY_FIELDS` intentionally
  excludes it — see `services/shared_platform_services.py`); resolving a
  `knowledge_references` record's MDU content still requires a separate
  call to `/mdu/schema/{id}` or `/mdu/provenance/{id}`, consistent with
  never duplicating MDU-owned content into MASTERDB's shared store.

## BCAES Canonical Registry

A separate, additive module (`bcaes_registry/`, `/bcaes/*` routes) also
lives in this repo — the ecosystem-wide product/capability/service
catalog plus production convergence tracking and a live reality snapshot.
It's independent of everything above (no shared state, no shared routes).
Full design, current status, and a corrected account of an earlier wiring
gap are in `BCAES_REGISTRY_ARCHITECTURE.md` — read that before touching
`bcaes_registry/`.

## Canonical Document Repository, Auth/RBAC, Persistence, Constitutional Definition

Three more additive passes since the BCAES Canonical Registry section
above:

- **BCAB/BCAES Canonical Document Repository** (`canonical_repository/`,
  `/canonical-repository/*`) — versioned document store for BCAB/BCAES
  content, currently placeholder text pending central population. Full
  design: `CANONICAL_REPOSITORY_ARCHITECTURE.md`.
- **Production hardening** (`auth/` module) — real JWT auth via
  `POST /auth/token`, RBAC now enforced (not just declared) on
  `canonical_repository` (all routes) and `bcaes_registry` (write
  routes, via `authority_boundaries`), opt-in disk persistence
  (`MASTERDB_STORAGE_DIR`), audit logging, `/health` + `/ready`. Full
  status including what's explicitly NOT done (real identity provider,
  monitoring, backup/DR, security/load testing):
  `PRODUCTION_HARDENING.md`.
- **Constitutional Runtime Definition** — a from-the-evidence writeup of
  what MASTERDB actually is, what it doesn't own, its runtime position,
  and a contract-status table for every adjacent service named across
  every task brief to date (most say "no integration code exists," and
  say so honestly): `CONSTITUTIONAL_RUNTIME_DEFINITION.md`.

**Open items for whoever picks this up next:**

- `AUTH_JWT_SECRET` is not set on the Render deployment — tokens issued
  there won't survive a restart until it is. See `.env.example`.
- `MASTERDB_STORAGE_DIR` is not set anywhere — the deployed instance is
  still pure in-memory. Turning persistence on also needs a Render
  persistent Disk attached (the default filesystem is ephemeral) — see
  `PRODUCTION_HARDENING.md`.
- No live contract exists yet for Bucket, InsightFlow/Pravah, PARIKSHAK,
  NIYANTRAN, RAJYA, KESHAV, SARATHI, PRANA, KARMA, or BHEX. PRANA's owner
  separately asked for raw database connection details that don't apply
  (MASTERDB has no standalone database) — that's pending the task lead's
  call on integration shape.
- Coordination with Shivam Pal (named owner of production
  infra/auth/persistence/observability going forward) has not happened
  yet as of this handover — a message was drafted but the sync itself is
  still open.
