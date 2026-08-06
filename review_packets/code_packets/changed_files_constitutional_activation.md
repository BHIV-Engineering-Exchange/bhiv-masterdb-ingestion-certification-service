# Changed Files — BCAES Bootstrap → Production Hardening → Constitutional Runtime Definition

Consolidated delta across three task briefs handled in sequence:
"BCAES Ecosystem Bootstrap & TANTRA Convergence", "MASTERDB Production
Convergence & Canonical Runtime Activation", and "MASTERDB Constitutional
Runtime Activation & Ecosystem Participation." `changed_files.md` (Task 4)
and `changed_files_bcaes.md` cover everything before this. All changes
below are additive — nothing from Tasks 1–4 or the original BCAES module
was restructured or removed, only wired in, hardened, or documented.

## New files

| File | Purpose |
|---|---|
| `canonical_repository/__init__.py`, `models.py`, `store.py`, `service.py` | BCAB/BCAES Canonical Document Repository — per-category documents, immutable hash-chained versions, RBAC-enforced access policy, opt-in disk persistence. |
| `auth/__init__.py`, `models.py`, `constants.py`, `service.py`, `dependencies.py` | Real JWT auth — HS256 signed/expiring tokens, `AuthIdentity` extraction, shared `bhiv-admin` admin role. |
| `CANONICAL_REPOSITORY_ARCHITECTURE.md` | Design doc for the canonical repository, including the access-control scope decision and its later reversal to real enforcement. |
| `PRODUCTION_HARDENING.md` | Status doc for auth/RBAC/persistence/audit-logging/health-readiness work; explicit list of what's still not done (monitoring, backup/DR, security/load testing, rate limiting) and why. |
| `CONSTITUTIONAL_RUNTIME_DEFINITION.md` | Phase 1 deliverable for the current brief — MASTERDB's identity, authority boundaries, runtime position, and a contract-status table for every named adjacent service. |
| `.env.example` | Previously missing; lists every real env var the app reads (`MDU_BASE_URL`, `MDU_API_KEY`, `AUTH_JWT_SECRET`, `MASTERDB_STORAGE_DIR`). |
| `tests/test_auth_service.py` | 6 tests — JWT issue/decode round trip, tamper rejection, cross-secret rejection, expiry, env-var secret handling. |
| `tests/test_bcaes_convergence_api.py` | 7 tests — Production Convergence (Volume 6) HTTP layer. |
| `tests/test_canonical_repository_api.py` | 20 tests — full canonical repository HTTP layer including RBAC allow/deny and admin-bypass cases. |
| `tests/test_persistence.py` | 6 tests — proves disk persistence survives a full service-instance replacement (the real shape of a process restart), for both `bcaes_registry` and `canonical_repository`. |
| `scripts/capture_bcaes_evidence.py`, `capture_canonical_repository_evidence.py` | Drive a live `TestClient` against the running app to generate `review_packets/api_responses_bcaes/` and `api_responses_canonical_repository/` — every captured response is real, not hand-written. |
| `scripts/seed_known_ecosystem_objects.py` | Registers only the ecosystem objects/owners the original BCAES brief explicitly names (TANTRA/Rajaryan, MDU/Nupur, Bucket/Ashmit, etc.) — deliberately excludes TMS and BCAB, for which no owner/role was ever given. |

## Modified files

| File | Change |
|---|---|
| `main.py` | Wired `bcaes_registry` (previously imported nowhere despite a module existing — see `BCAES_REGISTRY_ARCHITECTURE.md` §6 for that correction); added `canonical_repository`, `auth` wiring; `/auth/token`, `/health`, `/ready` endpoints; audit logging on every mutating call; `bcaes_registry` write routes and every `canonical_repository` route now require a verified bearer token. |
| `bcaes_registry/store.py`, `service.py` | Added `PermissionDeniedError`; optional `persist_dir` (disk persistence via `ArtifactStore`, opt-in, default unchanged/in-memory); `register`/`update`/`delete` accept optional `actor`/`actor_roles` and enforce against `authority_boundaries` when supplied. |
| `BCAES_REGISTRY_ARCHITECTURE.md` | Corrected the "136/136 passing" and working-routes claims that predated the actual wiring fix; documents real endpoint count, real test count, Volume 6/7 additions. |
| `README.md`, `ARCHITECTURE.md`, `API_DOCUMENTATION.md`, `HANDOVER.md` | Added the pointers to `BCAES_REGISTRY_ARCHITECTURE.md`/`CANONICAL_REPOSITORY_ARCHITECTURE.md` that earlier versions of these docs claimed existed but didn't; added `PRODUCTION_HARDENING.md` and `CONSTITUTIONAL_RUNTIME_DEFINITION.md` pointers. |
| `.gitignore` | Added `storage/`, `__pycache__/`, `*.pyc`, `.coverage`. |
| `requirements.txt` | Added `PyJWT`. |
| `review_packets/api_responses_bcaes/*`, `runtime_bcaes/*` | Deleted and regenerated from real live calls — the originals could not have been real (see `BCAES_REGISTRY_ARCHITECTURE.md` §6). |
| `review_packets/api_responses_canonical_repository/*` | Regenerated to include real 401/403/409 responses from the now-enforced auth/RBAC layer. |

## Net additions (this consolidated delta)

- 180 tests total (up from 96 at the end of Task 4), 97% statement
  coverage across `auth/`, `bcaes_registry/`, `canonical_repository/`
  combined.
- 4 new route groups: `/bcaes/*` (17 endpoints), `/canonical-repository/*`
  (9 endpoints), `/auth/token`, `/health` + `/ready`.
- Zero regressions in any pre-existing route or test across every pass.
