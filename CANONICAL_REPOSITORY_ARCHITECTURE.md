# BCAB/BCAES Canonical Document Repository — Architecture

## 1. What this is (and is not)

This is the secure, access-controlled repository the task lead asked for
on 2026-07-22, distinct from `bcaes_registry/` (which catalogs ecosystem
*objects* — products, capabilities, services). This module holds the
BCAB and BCAES Volume 1-7 **documents** themselves as the single source
of truth, with governed access, versioning, provenance, and an API
surface for future consumption by TANTRA and other services.

It is **not** populated with real content. Per the task lead's explicit
instruction: *"Don't implement against personal copies of the BCAB/BCAES
documents... We'll populate the canonical documents there once the
repository is ready."* Every document registered without explicit content
gets clearly-labeled placeholder text (see §4) so the API is
demonstrable end-to-end without anyone mistaking scaffolding for the real
thing.

## 2. Data model

- **CanonicalDocument** — one per `DocumentCategory` (`bcab`,
  `bcaes_vol_1` … `bcaes_vol_7`; a second document in the same category
  is rejected with 409, since one canonical home per category is the
  entire point). Carries `owner`, `status` (`placeholder` / `draft` /
  `published` / `deprecated`), `access_policy`, and `current_version`.
- **DocumentVersion** — immutable. Publishing a new version always
  appends; nothing is ever mutated in place. Each version's
  `content_hash` is `sha256(previous_hash + content)`, so the full
  history forms a hash chain — the same tamper/corruption-evidence idea
  as `bcaes_registry`'s `replay_hash`, applied per-document.
- **AccessPolicy** — `read_roles` / `write_roles` per document (defaults:
  `["ecosystem-reader"]` / `["bcaes-editor"]`).

## 3. Access control — schema now, enforcement later (confirmed 2026-07-22)

> **Update, 28 July 2026:** enforcement is now real — see
> `PRODUCTION_HARDENING.md`. `auth/` added real signed-token
> infrastructure and every route now checks `read_roles`/`write_roles`
> for real. The decision record below is kept as-is for history; treat
> "enforced later" in it as now done.

This repo has no real identity/auth layer anywhere yet — no login, no API
keys, nothing to check a role claim against. Two options were on the
table: fake enforcement against a self-declared identity, or build the
schema and defer enforcement. **Decision: schema now, enforce later.**

Every request already carries `actor` (required) and `roles` (optional,
comma-separated) as query params, and every document already declares
`read_roles`/`write_roles`. But nothing currently checks one against the
other — an actor with zero declared roles can publish a new version today
(see `test_access_policy_defaults_present_but_not_enforced`, which pins
this down deliberately so a future change here is a visible diff, not a
silent behavior change).

**Where enforcement plugs in later:** `canonical_repository/service.py`
methods already take `actor`/`actor_roles` as parameters but don't use
them yet. Adding
`if not set(actor_roles) & set(document.access_policy.write_roles): raise PermissionError(...)`
in the write methods (and the read equivalent) is the entire change —
nothing in `main.py`'s routes or `store.py`'s persistence needs to move.

## 4. Placeholder content

`RegisterDocumentRequest.initial_content` is optional. If omitted, the
service generates:

```
[PLACEHOLDER — not the real {category} text]

This is demo scaffolding for the BCAES Canonical Repository API. The
actual {category} content will be populated centrally by the BCAES task
owner once this repository is confirmed ready — see
CANONICAL_REPOSITORY_ARCHITECTURE.md. Do not treat this content as
authoritative for any architectural decision.
```

`DocumentVersion.is_placeholder` is `true` for that version, and the
document's `status` is `placeholder` rather than `draft`, so any consumer
(including TANTRA, once wired) can tell real content from scaffolding at
a glance without parsing the text.

## 5. API surface

All read/write endpoints take `actor` (required query param) and `roles`
(optional, comma-separated) — see §3 for why these aren't enforced yet.

```
POST   /canonical-repository/documents
GET    /canonical-repository/documents
GET    /canonical-repository/documents/{document_id}
GET    /canonical-repository/by-category/{category}
POST   /canonical-repository/documents/{document_id}/versions
GET    /canonical-repository/documents/{document_id}/versions
GET    /canonical-repository/documents/{document_id}/versions/{version_number}
GET    /canonical-repository/documents/{document_id}/latest
GET    /canonical-repository/documents/{document_id}/verify
```

`GET .../latest` is the endpoint meant for future TANTRA/other-service
consumption — always the current published (or placeholder) content
without the caller needing to track version numbers.
`GET .../verify` recomputes the whole hash chain from stored content and
reports whether it's intact — a corruption/tamper check, not an
authenticity guarantee (there's no signing yet, just hash-chained
integrity).

## 6. Persistence

In-memory, matching `bcaes_registry`'s explicit scope decision (see
`BCAES_REGISTRY_ARCHITECTURE.md` §5) — a data model + API contract, not a
persistence commitment. The same JSON-per-key `ArtifactStore` pattern used
elsewhere in this repo (`services/artifact_store.py`) is the natural next
step once this needs to survive a restart; nothing in `service.py` or
`main.py` would need to change, only `store.py`'s internals.

## 7. Testing

`tests/test_canonical_repository_api.py` — 15 tests, 99% statement
coverage on `canonical_repository/` (2 lines uncovered: an unreachable
guard in `verify_chain`'s empty-history edge case and one defensive
branch in `get_version`). Full repo suite: **158/158 passing** (143
pre-existing + 15 new), zero regressions.

## 8. Open items for the task lead

- Real content for each `DocumentCategory`, to replace the placeholders.
- A decision on real actor identity (how does a caller prove they're
  "Nupur" or "MDU", concretely?) before §3's enforcement can be turned on
  for real rather than schema-only.
- Confirmation of exactly which roles should exist ecosystem-wide (this
  pass only has the two defaults, `ecosystem-reader` / `bcaes-editor`) —
  likely one write role per team (Rajaryan/TANTRA, Nupur/MDU,
  Ashmit/Bucket, etc.) rather than one shared editor role.
- Whether TANTRA consumption should be pull (`GET .../latest`, as built)
  or push (this service notifying TANTRA on publish) — pull is what's
  built now since it needs no outbound network access this sandbox
  doesn't have.
