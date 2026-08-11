# MASTERDB — Constitutional Runtime Definition

Phase 1 deliverable for "MASTERDB Constitutional Runtime Activation &
Ecosystem Participation." This is a definition of what MASTERDB *already
is*, assembled from the existing architecture/contract docs and the code
itself — not a new design. Where something the brief asks for doesn't
exist yet, that's stated plainly rather than described as if it does.

## 1. Constitutional identity

MASTERDB is the canonical knowledge platform runtime for the BHIV
ecosystem. It owns:

- Dataset validation and certification (deterministic rule engine,
  `config/validation_rules.json`)
- Knowledge Package Lifecycle (directed state graph, replayable
  transition history)
- Dataset Registry and Package Identity
- Knowledge Object / Provenance *consumption* (not authority — see §2)
- Retrieval Readiness and Evidence
- The BCAES Canonical Registry (`bcaes_registry/`) — ecosystem-wide
  product/capability/service cataloging, production convergence
  tracking, live reality snapshot
- The BCAB/BCAES Canonical Document Repository
  (`canonical_repository/`) — versioned, access-controlled storage for
  the BCAB/BCAES documents themselves
- The Shared Data Service Registry (`shared_data/`) — 15 cross-dataset
  service definitions on a common versioned/audited/replay-safe engine
- A real SQL database backend (`services/sql_artifact_store.py`, opt-in
  via `MASTERDB_DATABASE_URL`) — "the central DB of BHIV" per the task
  lead (3 Aug 2026). External access remains through the authenticated
  API, not raw database credentials — see `DATABASE.md` for why.

Full component/data-flow detail: `ARCHITECTURE.md`.

## 2. Authority boundaries — what MASTERDB does NOT own

- **Canonical schemas, ontology, knowledge authority, governance, runtime
  reasoning, embeddings, vector databases** — owned by MDU (Nupur) and
  downstream reasoning systems (TANTRA). MASTERDB *consumes* MDU's
  contract via `MDUContractAdapter`; it does not define it. See
  `MDU_INTERFACE_CONTRACT.md`.
- **BCAB/BCAES canonical *content*** — MASTERDB hosts the repository
  infrastructure (versioning, access control, integrity verification) but
  does not author the documents. Per the task lead's explicit instruction
  (22 July 2026), content is populated centrally, not from personal
  copies. Every document in the repository right now is placeholder text,
  clearly labeled as such — see `CANONICAL_REPOSITORY_ARCHITECTURE.md`.
- **Systems observability tooling going forward** — per the latest brief
  (Integration Coordination doc), Shivam Pal owns Pravah specifically:
  runtime health monitoring, readiness checks, operational health
  endpoints, status reporting. `/health` and `/ready` already satisfy
  this scope; built before that assignment landed. The task lead
  clarified (3 Aug 2026) this doesn't actually conflict with what
  MASTERDB owns — Shivam Pal's is a "systems observability layer,"
  MASTERDB's `/metrics` (§4) is a "data observability layer." They're
  different things, per the lead, not duplicate ownership. Earlier
  drafts of this doc described a broader, now-superseded "production
  infra/auth/persistence/observability" scope for him from a prior
  brief; that framing is stale — see `PRODUCTION_HARDENING.md` for
  what's actually built and by whom.
- **Identity/authentication of real people** — `auth/` issues real signed
  tokens but does not verify who's requesting one; no login/SSO exists
  anywhere in the ecosystem yet, per every prior integration
  conversation in this task's history.
- **Real Central Depot / BHEX archival** — MASTERDB has never had network
  access to whatever system this actually is; nothing has been deposited
  anywhere outside this repo.

## 3. Runtime position

MASTERDB sits as a **downstream consumer of MDU** and an **upstream
provider to TANTRA and adjacent services**:

```
MDU (schema/provenance authority)
  → MDUContractAdapter → MASTERDB (validation, certification, lifecycle)
       → TantraInterfaceService → TANTRA (runtime discovery, execution)
       → RuntimeDiscoveryService → (package/capability queries)
       → bcaes_registry / canonical_repository → (ecosystem catalog + docs)
```

It is not itself a runtime orchestrator, a scheduler, or an execution
engine — every write is a direct API call/response, not an
asynchronously-executed task. "Runtime participation" for MASTERDB today
means: it can be called synchronously by another service and returns a
deterministic, replayable result. It does not currently *call out* to
adjacent services proactively (push), only respond to being called
(pull) — see §6 for what "runtime registration" would require to change
that.

## 4. Adjacent services and current contract status

| Service | Contract status | Where |
|---|---|---|
| MDU (Nupur) | Live client exists (`services/mdu_client.py`), degrades gracefully if `MDU_BASE_URL`/`MDU_API_KEY` unset | `MDU_INTERFACE_CONTRACT.md` |
| TANTRA (Rajaryan Verma) | `GET /runtime/identity` now exposes a self-description manifest for TANTRA's Runtime Registry to read — but no live registry endpoint has been confirmed reachable, so no actual registration call has been made. `status: "not_yet_registered"` in the manifest itself, deliberately. | `main.py`, `tests/test_runtime_identity_and_metrics.py` |
| Bucket (Siddhesh Narkar) | A URL now exists (`PRAVAH_BHIV_BUCKET`) but responds ambiguously (404 on root — could be real, could be nothing; see `ECOSYSTEM_ENDPOINTS.md`). No confirmed contract for evidence-publishing yet, so no client built against a guess. | `ECOSYSTEM_ENDPOINTS.md` |
| Pravah (Shivam Pal) | `/health`, `/ready` already exist and satisfy his listed scope (runtime health/readiness/status) — see §2 for the ownership note. | `main.py` |
| InsightFlow/InsightBridge/InsightCore (Vijay Dhawan) | **InsightBridge confirmed live (6 Aug 2026)** — real client (`services/insightbridge_client.py`) + `POST /observability/push-to-insightbridge`, degrades gracefully if `PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE` unset. Payload shape is still an assumption (couldn't fetch the real OpenAPI spec — see `ECOSYSTEM_ENDPOINTS.md`), pending Vijay Dhawan's confirmation. `GET /metrics` (pull-based, Prometheus format) also still exists as a separate, unconfirmed-format option. InsightCore and the other InsightFlow candidate URL are ambiguous (404 on root) — see `ECOSYSTEM_ENDPOINTS.md`. | `services/insightbridge_client.py`, `main.py`, `ECOSYSTEM_ENDPOINTS.md` |
| PARIKSHAK (engineering review) | `/parikshak/review-references` (POST requires `parikshak-sync` role or admin; GET public) exists — MASTERDB can ingest and store references/summaries/readiness now. Direction is an assumption (MASTERDB ingests pushed records; see `operational_sync/models.py`) since no PARIKSHAK "approved review API" has been confirmed reachable to poll instead. | `operational_sync/`, `main.py` |
| NIYANTRAN (operational task lifecycle) | `/niyantran/task-state` (same auth pattern) exists — records candidate/progress/status only, zero workflow-execution logic by construction (proven in `test_niyantran_store_has_no_execution_side_effects`). Same direction assumption as PARIKSHAK. | `operational_sync/`, `main.py` |
| Replay Registry Owner | `GET /replay-registry/manifest` exposes MASTERDB's own replay-capable surfaces (bcaes_registry replay_hash, canonical_repository per-document hash chain, package lifecycle replay) — self-description only, `status: "not_yet_registered"`. No named owner or endpoint exists to register with yet. | `main.py` |
| RAJYA, KESHAV, SARATHI, PRANA, KARMA, BHEX | No contracts received for any of them. PRANA's owner separately requested raw database connection details — resolved: MASTERDB now has a real database (`DATABASE.md`), but external access is still via the authenticated API, not raw credentials, per that doc's explicit reasoning. | `DATABASE.md` |

The pattern across every "no integration code exists" row is the same:
building a client against an unconfirmed, unreachable contract produces
exactly the kind of fabricated-looking evidence this task's history has
already had to correct once (see `BCAES_REGISTRY_ARCHITECTURE.md` §6 and
`REVIEW_PACKET.md`). Nothing here is stubbed to *look* integrated without
being integrated.

## 5. Contracts, evidence, and replay — what's real today

- **Contracts**: `MDU_INTERFACE_CONTRACT.md` (draft, pending Nupur's
  joint sign-off — MDU repo access still needed to confirm MDU-owned
  field assumptions).
- **Evidence**: `review_packets/` — every capture in there is generated
  by a script that drives a live `TestClient` against the actually-
  running app (see the scripts in `scripts/`), not hand-written or
  assumed. Includes real 401/403/409 responses from the auth/RBAC layer,
  not just happy-path calls.
- **Replay**:
  - `PackageRegistryService.replay()` rebuilds a package's status from
    its full transition history.
  - `bcaes_registry`'s `validate/architecture` endpoint produces a
    `replay_hash` that's identical across repeated calls against
    unchanged state (proven in `tests/test_bcaes_registry_service.py`).
  - `canonical_repository`'s `/verify` endpoint recomputes a document's
    entire hash chain from stored content and reports tamper/corruption.
  - `tests/test_persistence.py` proves data survives a full service-
    instance replacement (the actual shape of a process restart), not
    just that persistence code runs without erroring.

## 6. Observability — current state

- Structured logging exists (`logger`, `masterdb` namespace) for
  registration/transition/MDU-call events.
- A dedicated `audit_logger` (`masterdb.audit`) exists for every
  mutating `bcaes_registry`/`canonical_repository` call — actor, action,
  resource id.
- `GET /health` (liveness) and `GET /ready` (readiness, checks both
  stores are reachable) exist.
- `GET /metrics` exists — Prometheus text format, gauge counts per
  BCAES registry type and canonical document count. Built for
  InsightFlow/Vijay Dhawan's telemetry consumption (§4); format is an
  assumption pending his confirmation, not a confirmed contract.
- **No tracing or dashboards exist.** No OpenTelemetry, no collector
  exporting anywhere — `/metrics` is scrapable but nothing scrapes it
  yet, since no InsightFlow endpoint/contract has been confirmed
  reachable from this environment.

## 7. What Phase 1 does NOT resolve

This doc defines MASTERDB's current, actual position — it does not
itself achieve "plug-and-play" runtime participation (Phase 5 of the
current brief), which requires the live registrations and contracts in
§4 that don't exist yet. Treat this as the honest baseline the later
phases build from, not a claim that those phases are already done.
