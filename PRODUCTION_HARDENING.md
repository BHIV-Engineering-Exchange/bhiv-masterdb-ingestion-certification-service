# Production Hardening — Status Against "MASTERDB Production Convergence & Canonical Runtime Activation"

Task brief dated 28 July 2026. This doc tracks Phase 2 (Enterprise
Hardening) specifically — the pieces genuinely buildable in a sandboxed
dev environment with no live network access to any BHIV system. For the
rest of the brief's phases, see the status table this was built alongside
(shared with the task owner) — short version: Phase 6 (live TANTRA/RAJYA/
KESHAV/SARATHI/MDU/Bucket/Pravah/InsightFlow/PRANA/KARMA integration) and
Phase 7 equivalents remain blocked on real access/credentials this
environment does not have.

## What's real now (this pass)

### Authentication — `auth/`
- `POST /auth/token` issues an HS256-signed, expiring JWT for a caller-
  supplied `actor`/`roles`.
- Every write route on `bcaes_registry` and **every** route (read and
  write) on `canonical_repository` requires `Authorization: Bearer
  <token>`. Missing/invalid/expired/tampered tokens get a real 401.
- **What this is not**: proof of identity. There's no login, password, or
  SSO anywhere in this repo — `/auth/token` signs whatever `actor`/`roles`
  it's told. See `auth/service.py`'s module docstring for the exact
  boundary. Closing this requires a real identity provider
  (OAuth2/SSO/whatever BHIV standardizes on) issuing tokens instead of
  this endpoint — everything downstream (verification, RBAC) doesn't
  change when that happens.

### Authorization / role enforcement
- `bcaes_registry`: write operations (register/update/delete) check the
  caller against the object's `authority_boundaries` (existing field,
  now actually enforced) or the shared `bhiv-admin` role
  (`auth/constants.py`). Reads remain open — no `authority_boundaries`-
  style concept existed for reads before this pass, and adding one is a
  bigger schema change than this pass scoped.
- `canonical_repository`: both reads and writes now check the caller's
  roles against the document's declared `read_roles`/`write_roles` (this
  was schema-only/unenforced before — see
  `CANONICAL_REPOSITORY_ARCHITECTURE.md` §3 for that earlier decision).
  `list_all` filters to readable documents rather than 403ing the whole
  call.
- Both modules' service layers accept `actor`/`actor_roles` explicitly
  rather than pulling them from a global/thread-local — direct/
  programmatic callers (including most existing tests) that don't pass
  an actor bypass enforcement entirely, by design: enforcement is an
  HTTP-layer concern that `main.py` always applies for real traffic, not
  a mandatory property of the domain objects themselves.

### Persistent storage
- Opt-in via `MASTERDB_STORAGE_DIR` (unset = pure in-memory, matching
  every existing test's isolation assumptions and every behavior before
  this pass). Set, both `bcaes_registry` and `canonical_repository`
  mirror every write to JSON files (`services/artifact_store.py`
  pattern, already used elsewhere in this repo) and reload on startup.
  Proven with `tests/test_persistence.py`, which constructs a fresh
  service instance against the same directory (the actual shape of "the
  process restarted") and confirms the data survived.
- **Render caveat**: on Render's default (non-Disk) instance types, the
  filesystem is wiped on every deploy and every restart, regardless of
  this setting. Real persistence in production requires attaching a
  persistent Disk in Render's dashboard and setting
  `MASTERDB_STORAGE_DIR` to a path under that disk's mount point. This
  hasn't been done — it's a Render dashboard action, not something this
  environment can perform.

### Audit logging
- `audit_logger` (`masterdb.audit`) logs every mutating call
  (register/update/delete on `bcaes_registry`; register/publish_version
  on `canonical_repository`) with actor, action, and resource id.
  Currently stdout-only, same as the rest of this repo's logging — a
  real deployment would ship this to a dedicated sink (see "Not done"
  below).

### Health / readiness
- `GET /health` — liveness only, no dependency checks.
- `GET /ready` — checks both stores are reachable; returns 503 on
  failure. Deliberately does not check TANTRA/MDU/Bucket/InsightFlow
  connectivity, since this service has no live connection to any of them
  to check.

## What's NOT done, and why

- **Real identity/SSO.** See above — this is the load-bearing gap
  everything else in this section sits on top of.
- **Monitoring/observability (OpenTelemetry, dashboards, alerting).**
  Needs a real collector/backend (Prometheus, Datadog, whatever BHIV
  standardizes on) to send to; nothing to wire up against in this
  sandbox.
- **Backup/disaster recovery.** Meaningless without real, non-ephemeral
  production storage to back up (see the Render Disk caveat above) — the
  file-based persistence here is the prerequisite, not the backup
  strategy itself.
- **Security validation (penetration testing, dependency scanning as a
  gate, secrets scanning in CI).** Needs to run against a real deployed
  target and, for some of it, real tooling/services this environment
  doesn't have.
- **Performance/scalability/load testing.** Same — needs to run against
  the real deployed instance under real or simulated load, not a
  sandboxed dev process.
- **Rate limiting.** Not implemented. A real production API gateway or
  middleware layer (not built this pass) is the natural place for this.

## Testing evidence

`tests/test_auth_service.py` (6), plus new/updated coverage across
`tests/test_bcaes_api.py`, `tests/test_bcaes_convergence_api.py`,
`tests/test_canonical_repository_api.py`, and `tests/test_persistence.py`
(6, proving actual disk round-trip via fresh service instances). Full
suite: **180/180 passing**, 97% statement coverage across `auth/`,
`bcaes_registry/`, `canonical_repository/` combined.

## Before treating this as production-certified

1. Set `AUTH_JWT_SECRET` in Render's environment variables (a real
   secret, not left blank — see `.env.example`).
2. Decide on and wire a real identity provider for `/auth/token`, or
   replace it with whatever BHIV's actual SSO/auth pattern is.
3. Attach a persistent Disk in Render and set `MASTERDB_STORAGE_DIR` to a
   path on it, if this instance needs to survive restarts (it currently
   doesn't have this configured).
4. Everything under Phase 6/7 of the task brief — live integration with
   the ecosystem and Central Depot/BHEX deposit — still needs real access
   this environment doesn't have.
