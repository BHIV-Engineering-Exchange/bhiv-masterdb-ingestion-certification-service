# MASTERDB — Database

Delivered in response to the task lead (3 Aug 2026): *"under MasterDB you
will be creating a database. This will be the central DB of BHIV."*

## What this is

A real SQL database backend (`services/sql_artifact_store.py`, via
SQLAlchemy), opt-in via `MASTERDB_DATABASE_URL`, backing both
`bcaes_registry` and `canonical_repository`. Set the env var and both
services persist to real tables instead of JSON files or memory — proven
end-to-end (real `main.app`, real HTTP calls, simulated restart) in
`tests/test_sql_database.py`.

- **Default for local dev**: `sqlite:///path/to/file.db` — a real
  relational database, zero external services to stand up.
- **Real production**: any Postgres connection string
  (`postgresql://user:pass@host:port/dbname`). Nothing in the code
  changes — SQLAlchemy's dialect handling is what makes this work; only
  the env var value changes.
- **One database, two services**: `bcaes_registry` and
  `canonical_repository` can point at the *same*
  `MASTERDB_DATABASE_URL` safely — each partitions its rows by a
  `store_name` column rather than needing separate databases (proven in
  `test_bcaes_registry_and_canonical_repository_can_share_one_database_url`).

## Schema

One table, `artifact_records`: `(store_name, key, value_json,
updated_at)`, primary-keyed on `(store_name, key)`.

**Why not one table per registry type / document type**: the eleven
BCAES registry types and the canonical document/version records are
genuinely heterogeneous, evolving Pydantic shapes. A single JSON-value
table gives real transactional writes and real indexed point-lookups
today without a schema migration every time a registry type gains a
field. This is the same trade `ArtifactStore` (the JSON-file backend)
already made — this class keeps that interface (`save`/`load`/
`list_all`/`delete`) so `bcaes_registry` and `canonical_repository`
didn't need any logic changes, only a new backend option.

**Natural next step, not done here**: a normalized schema per registry
type once the shapes stabilize enough to be worth migrating. This table
is what any such migration would read its source data from.

## What this deliberately does NOT do

**External services do not get raw database credentials.** This is a
direct response to the PRANA integration request (their contact asked
for DB type, connection URI, username/password, IP whitelisting) — that
request assumed a database existed to hand out access to, and now one
does, but handing out `MASTERDB_DATABASE_URL` directly would:

- Bypass the JWT auth and RBAC enforcement built in the previous pass
  entirely — anyone with the connection string reads/writes everything,
  no `authority_boundaries` or `read_roles`/`write_roles` check applies
  at the database layer.
- Bypass audit logging — direct SQL writes never touch `audit_logger`.
- Create a second way for data to become inconsistent — the API layer's
  validation (dependency existence checks, duplicate-category rejection,
  hash-chain integrity) only runs when data goes through the API, not
  when someone writes directly to the table.

External services — PRANA included — reach this data the same way
everything in this repo already works: authenticate via `POST
/auth/token`, call the `/bcaes/*` or `/canonical-repository/*` API with
a role-appropriate token. The database existing doesn't change that
contract; it changes what's behind it.

If direct database access for specific trusted internal tooling
(analytics, reporting) is genuinely wanted later, that's a distinct,
narrower decision — e.g. a read-only replica or a dedicated reporting
user — not the same credential that can write through this table.

## Setup

```
# .env or Render environment variables
MASTERDB_DATABASE_URL=postgresql://user:password@host:5432/masterdb
```

Leave unset to keep the existing behavior: `MASTERDB_STORAGE_DIR` (JSON
files) if that's set, otherwise pure in-memory. `MASTERDB_DATABASE_URL`
takes priority over `MASTERDB_STORAGE_DIR` when both are set.

## Testing

`tests/test_sql_database.py` — 10 tests: `SqlArtifactStore` CRUD and
store-name partitioning directly, plus both services proven to persist
across a full service-instance replacement (the real shape of a
restart) when backed by SQL instead of JSON. Full suite: **190/190
passing** (180 + 10 new), no regressions to existing in-memory/JSON-file
behavior — both remain the default and are what every existing test
still uses.
