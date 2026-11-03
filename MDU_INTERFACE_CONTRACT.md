# MASTERDB <-> MDU Interface Contract v1

**Status: DRAFT.** Transport (Phase 1) is now live — MASTERDB can reach
MDU's real endpoints via `services/mdu_client.py` / `MDUContractAdapter`.
Semantics (field shapes, identity ownership, versioning policy) are still
**pending joint sign-off with Nupur** and remain placeholder assumptions
below until confirmed. MASTERDB does not redefine any of the concepts
below — it documents its current *consumption* of them so the seam is
explicit and auditable.

## Live Transport (Phase 1)

`MDUClient` (`services/mdu_client.py`) is the only module aware of MDU's
base URL, auth header, and paths. Configure it via environment variables —
credentials are never hardcoded:

```
MDU_BASE_URL=https://parakosha.blackholeinfiverse.com
MDU_API_KEY=<the shared key>
```

Endpoints it calls, mapped 1:1 to what MDU publishes:

| MASTERDB adapter method         | MDU endpoint                                          |
|----------------------------------|--------------------------------------------------------|
| `fetch_schema_contract`          | `GET /api/v1/schemas/dataset/{dataset_id}`             |
| `fetch_provenance_contract`      | `GET /api/v1/datasets/{dataset_id}/provenance`         |
| `fetch_canonical_dataset`        | `GET /api/v1/datasets/canonical/{dataset_id}`          |
| (client) `validate_all_provenance` | `GET /api/v1/discovery/provenance/validate-all`      |
| (client) `get_discovery_summary`   | `GET /api/v1/discovery/summary`                      |

MASTERDB's `ds-gev-seismic-events` identifier maps to MDU's registered
canonical ID `BHIV-DS-GEV-SEISMIC-EVENTS-001`; MDU requires canonical IDs
to use its `BHIV-DS-{DOMAIN}-{NAME}-{NUMBER}` format.

Exposed over HTTP for ops visibility at `GET /mdu/status`,
`GET /mdu/schema/{dataset_id}`, `GET /mdu/provenance/{dataset_id}`, and
`GET /mdu/schema-compatibility/{dataset_id}?local_schema_version=...`.

If MDU is unconfigured or unreachable, `validate_schema_compatibility`
degrades to the placeholder (permissive, flagged) rule below rather than
hard-failing package registration — MASTERDB should never go down purely
because MDU is temporarily unavailable.

**Not yet verified against a live response:** this client was built and
unit-tested against the documented endpoint *shapes*, but could not be
exercised against the actual running MDU service from the sandbox this was
built in (no outbound network access there). Before merging, run it against
the real `MDU_BASE_URL` in a networked environment and confirm the actual
JSON field names (`schema_version` vs `version`, etc.) match what
`validate_schema_compatibility` expects — adjust the two `.get(...)` lookups
in `MDUContractAdapter.validate_schema_compatibility` if they don't.


## Ownership

| Concept                     | Owner | MASTERDB's role                     |
|------------------------------|-------|--------------------------------------|
| Knowledge Object semantics    | MDU   | Consumer only, via `MDUContractAdapter` |
| Provenance schema             | MDU   | Consumer only                         |
| Lineage graph semantics       | MDU   | Consumer only (walks parent/child pointers it is given) |
| Canonical dataset schema       | MDU   | Consumer only (`schema_version` is opaque to MASTERDB) |
| Package Identity              | MASTERDB | Owner (`package_id`, lifecycle status) |
| Dataset Registry               | MASTERDB | Owner |
| Retrieval Readiness/Evidence   | MASTERDB | Owner |

## Consumed Contracts

MASTERDB currently consumes the following MDU-owned concepts, through
`services/mdu_contract_adapter.py::MDUContractAdapter`:

- **Knowledge Object identity** — MASTERDB currently generates its own
  `knowledge_object_id` and `knowledge_hash` (sha256 of `package_id` +
  `source_reference` + `derivation_path`) as a placeholder. **Not yet
  confirmed by MDU** whether this should instead be assigned or validated
  by MDU's own identity scheme.
- **Provenance `source_reference`** — treated as an opaque string (assumed
  URI/path). **Not yet confirmed** against MDU's canonical provenance
  schema.
- **Lineage `lineage_reference`** — treated as an optional opaque pointer.
  **Not yet confirmed** against MDU's lineage graph representation.
- **`derivation_path`** — treated as an ordered list of free-text
  transformation step names. **Not yet confirmed** — MDU may define a
  richer, typed representation.

## Required Fields (MASTERDB side, current placeholder)

| Field                | Required | Confirmed by MDU | Notes |
|-----------------------|----------|-------------------|-------|
| `knowledge_object_id` | Yes      | No                | MASTERDB-generated; format pending MDU review |
| `source_reference`    | Yes      | No                | Assumed opaque string |
| `lineage_reference`   | No       | No                | Optional pointer, shape TBD |
| `derivation_path`     | No       | No                | Ordered string list, shape TBD |
| `parent_package`      | No       | N/A (MASTERDB-owned) | References a MASTERDB `package_id`, validated to exist in the registry |
| `schema_version`      | Yes      | No                | Opaque to MASTERDB; only major-version prefix is compared for compatibility |

## Version Compatibility

MASTERDB currently enforces a **placeholder** compatibility rule: a child
package's `schema_version` must share the same major-version prefix (text
before the first `.`) as its declared parent's `schema_version`. This is a
conservative stand-in and is explicitly **not** a claim about MDU's actual
schema evolution policy. It should be replaced once MDU defines real
compatibility semantics (e.g. semantic versioning rules, migration
requirements, or a compatibility matrix).

## Known Gaps

1. MDU's canonical Knowledge Object contract has not been finalized or
   shared as of this sprint — this document and `MDUContractAdapter`
   reflect MASTERDB's best-effort placeholder, not a ratified spec.
2. Identity assignment for `knowledge_object_id` may need to move to MDU or
   be validated against an MDU-issued scheme.
3. Version compatibility rules are a placeholder (major-version equality)
   pending MDU's real policy.
4. No confirmed schema for `lineage_reference` or `derivation_path` exists
   yet; both are currently unstructured.
5. ~~"Runtime Discovery" does not yet have a dedicated endpoint~~ — resolved:
   see `GET /discovery/packages` (`RuntimeDiscoveryService`), filterable by
   `package_id`, `dataset_id`, `board`, `medium`, `version`, and `status`.

## Future Extension Points

- Swap `MDUContractAdapter`'s placeholder snapshot for a live contract
  fetched from or validated against MDU once Phase 5 convergence with
  Nupur completes. `KnowledgeObjectService` was written to depend only on
  this adapter seam, so this should not require changes to lifecycle or
  retrieval logic.
- Add a dedicated Runtime Discovery endpoint if MDU or downstream
  consumers need a distinct service/tool discovery contract beyond package
  lookup.
- Extend `RetrievalEvidence` rules if MDU introduces additional
  provenance-completeness requirements that should gate retrieval.
- Replace the major-version compatibility placeholder once MDU's version
  compatibility policy is confirmed.

## No Duplicate Ownership

This document intentionally avoids redefining Knowledge Object, Provenance,
Lineage, or canonical schema semantics. Where MASTERDB's code currently
makes an assumption about their shape, it is called out above as a
placeholder and localized to `services/mdu_contract_adapter.py` so that a
future MDU-confirmed contract can replace it without touching
`PackageRegistryService` or `RetrievalReadinessService`.
