# MASTERDB Database Targets — Controlled Ingestion Attachment

Kavy's half of the "MASTERDB Dashboard & Control Center" convergence task
(see task assignment PDF, 26 Aug 2026). Rahil owns the dashboard/control-
center UI/UX; this module is the MASTERDB-side integration surface it
talks to for database discovery and controlled ingestion.

## What this is (and isn't)

This **attaches** the existing, already-built ingestion/certification
pipeline (`ValidationService` -> `CertificationService`, see main
`README.md`) to the 8 MASTERDB target databases. It does **not**
duplicate or rebuild that pipeline, and it does not implement the 8
databases' own storage engines — those are each database's own concern
and out of scope for this convergence task. What this module owns is the
**controlled boundary** between "a dataset is CERTIFIED" and "a dataset
is routed to the correct, explicitly authorized target database" —
RBAC, format contract, the certification gate, and the auditable
ingestion-job record that proves it happened correctly.

## The 8 target databases

Defined in `database_targets/registry.py`, discoverable live at
`GET /databases`:

| Database | Purpose | Accepted formats | Required role |
|---|---|---|---|
| VectorDB | Embeddings, semantic search | json, csv | `ingest:vectordb` |
| GraphDB | Knowledge graph, relationships | json, csv | `ingest:graphdb` |
| MetadataDB | Dataset registry, metadata | all | `ingest:metadatadb` |
| DocumentDB | Documents, unstructured data | pdf, txt, image, json | `ingest:documentdb` |
| TimeSeriesDB | Sensor, telemetry, time-series | csv, json | `ingest:timeseriesdb` |
| RelationalDB | Structured, tabular data | csv, xlsx, json | `ingest:relationaldb` |
| ArchiveDB | Long-term storage, cold data | all | `ingest:archivedb` |
| AnalyticsDB | Aggregated, analytical datasets | csv, json, xlsx | `ingest:analyticsdb` |

Adding a 9th database is additive: one new entry in the registry, nothing
else in this module changes, and the dashboard picks it up automatically
through `GET /databases`.

## Control chain (`POST /ingest`)

Every ingestion request runs through four steps, in order, and **every**
step — pass or fail — is recorded on the resulting `IngestJob`:

1. **RBAC_CHECK** — the authenticated actor's roles (from the JWT, see
   `auth/`) must include the target database's `required_role`, or
   `bhiv-admin` (see `auth/constants.py`). Visibility of a database via
   `GET /databases` never implies write authority.
2. **FORMAT_CHECK** — the declared `source_format` must be in that
   database's accepted-formats list. Deterministic, per the task's
   "reject invalid input deterministically" requirement.
3. **CERTIFICATION_GATE** — the dataset must already be in the
   `CERTIFIED` state with `eligible_for_masterdb=true`, as decided by the
   existing `CertificationService` (`POST /certify`). This module reads
   that decision from the same artifact store; it never recomputes it.
   Unknown/uncertified datasets are rejected — "Unknown/Quarantined is
   valid" per the task's control principles, and never becomes canonical
   merely because an ingestion request was made.
4. **ROUTED** — only reached if the first three pass. The routing
   decision is persisted; the physical write into the target database's
   own engine is that database's concern.

A rejection at any step still produces a persisted, retrievable
`IngestJob` with the full step trail — rejected attempts are as auditable
as successful ones.

## API surface (for the dashboard)

All endpoints require a bearer token from `POST /auth/token` (see main
`README.md` / `API_DOCUMENTATION.md` for the auth flow itself).

- `GET /databases` — list all 8 targets with capabilities/status.
- `GET /databases/{key}` — single target's capability contract.
- `POST /ingest` — submit an ingestion request:
  ```json
  {
    "dataset_id": "certifiable",
    "target_database": "RelationalDB",
    "source_format": "csv",
    "package_id": "optional-knowledge-package-id",
    "metadata": {}
  }
  ```
  Returns `201` + the `IngestJob` on success; `403` if the RBAC step
  failed; `422` if the format or certification step failed (error message
  includes the `job_id` so the full step trail is still retrievable).
- `GET /ingest/jobs/{job_id}` — full job detail: steps, actor, roles,
  certification state, integrity score, timestamps, rejection reason.
- `GET /ingest/jobs?dataset_id=&target_database=&status=` — filterable
  job list, for the dashboard's ingestion-activity/audit views.

## RBAC model

Roles follow `ingest:<database-key>` (lowercase), one per database, so
read/write/ingest/modify/export/admin authority stay separable as
required by the task — holding `ingest:vectordb` grants nothing on
`GraphDB`. `bhiv-admin` (`auth/constants.py`) bypasses all of them,
matching the single ops-bypass-role pattern already used by
`bcaes_registry`/`canonical_repository`. Tokens are self-declared at
`POST /auth/token` (see `auth/service.py`'s honesty note about what that
does and does not prove) — wiring a real identity provider later is a
drop-in replacement, nothing downstream of `get_identity` changes.

## Test coverage

- `tests/test_database_router_service.py` — service-level: discovery,
  unknown database, RBAC denial, format rejection, uncertified-dataset
  rejection, successful ingestion, admin bypass, job filtering.
- `tests/test_database_targets_api.py` — API-level, over real HTTP via
  `TestClient`: auth required (401), RBAC denial (403), uncertified
  dataset (422), successful ingestion (201) + job retrieval/listing.

Run: `python -m pytest tests/test_database_router_service.py
tests/test_database_targets_api.py -v` (or the full suite — this module
adds 14 tests to the existing 266, all passing).

## Known limitations / next steps

- The physical persistence layer for each of the 8 databases (actual
  VectorDB/GraphDB/etc. storage engines) is not implemented here — this
  module proves the routing decision is correctly gated and auditable,
  which is what was in scope; wiring each `ROUTED` outcome to a real
  storage backend is the next increment once those engines exist/are
  reachable.
- Ingestion job records use the same `ArtifactStore` JSON-file pattern as
  the rest of the repo (`ingestion_jobs_store/`), so they inherit the same
  opt-in `MASTERDB_STORAGE_DIR`/`MASTERDB_DATABASE_URL` persistence
  story documented in the main `README.md` and `DATABASE.md`.
- `package_id` on `IngestRequest` is accepted and stored for provenance
  linking to the Knowledge Package Lifecycle (`/packages/*`) but is not
  yet cross-validated against the registry — a reasonable follow-up once
  Rahil's UI confirms whether ingestion is always package-scoped.
