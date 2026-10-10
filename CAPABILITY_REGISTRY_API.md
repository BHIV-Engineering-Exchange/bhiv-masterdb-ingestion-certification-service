# Capability Registry and GEO-QUEST Candidate APIs

All routes require a bearer token. Capability registration and all GEO-QUEST
candidate routes require the `bhiv-admin` role.

## Capability registration and discovery

- `POST /capabilities/register` registers a capability version using a
  `Capability` JSON object. A repeated capability ID/version returns `409`;
  each distinct version is retained as an immutable snapshot.
- `GET /capabilities?domain=&status=&search=` filters capability metadata.
- `GET /capabilities/{capability_id}/versions` returns registered versions.
- `GET /capabilities/{capability_id}/contract` resolves its machine-readable
  contract and MDU schema/provenance references.
- `POST /access/request` evaluates capability status, required roles, allowed
  consumer, requested version, and purpose.
- `POST /capabilities/{capability_id}/retrieve` returns capability data only
  under a matching access grant (or freshly authorized request). Issued grants
  are bound to the authenticated actor as well as the application, capability,
  version, and retrieval scope; another actor cannot replay a grant token or
  request ID.

## GEO-QUEST candidate-only integration

The candidate routes stage the validated Source → Dataset → Capability
bundle for `adsb.lol`, `BHIV-GEO-QUEST-01-AIRCRAFT`, and
`gev.aircraft_tracking`. The candidate remains
`PENDING_AUTHORIZATION`, non-canonical, and non-discoverable. These routes do
not create an official MasterDB ID, publish the capability, or activate
production/service-bus access.

Registration checks raw/cleaned/quarantine count conservation, all six
passing quality gates, schema conformance, unique aircraft identifiers,
coordinates, numeric ranges, and record-level provenance. Retrieved records
are actual values from the normalized snapshot; an integrity digest detects
post-registration record modification.

- `POST /geo-quest/candidates/gev.aircraft_tracking/register` validates and
  stages the candidate bundle. The response includes the MDU schema-contract
  and version-compatibility results (live if configured, otherwise the
  explicitly labeled local version fallback).
- `GET /geo-quest/candidates/{capability_id}` returns candidate metadata,
  schema, and quality evidence.
- `POST /geo-quest/candidates/{capability_id}/retrieve` returns matching
  snapshot records. Optional fields are `center_latitude`,
  `center_longitude`, `search_radius_nm`, `filter_hex_id`,
  `filter_callsign`, `limit`, and `offset`.

Canonical publication, discoverability, and production reuse still require
the formal governance approval recorded in
[`MASTERDB-GEO-QUEST-01/README.md`](./MASTERDB-GEO-QUEST-01/README.md).

## God’s Eye View geospatial evidence candidates

The GEV export is validated and staged through the existing GEO-QUEST
candidate artifact store; it does not create a second registry. Set
`GEV_MASTERDB_IMPORT_DIR` to the export's `masterdb_import` folder when it is
not available at the sibling-repository default. Import rejects inconsistent
manifest/record/sidecar inventories, invalid schemas or geometries, provenance
and license mismatches, and modified staged artifacts. Registration is
idempotent for an identical export and refuses to replace a changed packet.

- `POST /geo-quest/imports/register` validates and stages the export.
- `GET /geo-quest/imports/candidate` returns candidate metadata and validation
  state.
- `POST /geo-quest/imports/candidate/retrieve` accepts `dataset_id` and
  `purpose`; retrieval is restricted to `purpose: "registry_review"`.

All three routes require `bhiv-admin`. The packet remains
`PENDING_AUTHORIZATION`, noncanonical, and absent from ordinary capability
discovery. Current records have no canonical MDU dataset IDs or typed MDU
field mappings, so MDU validation remains pending and is not asserted as
compatible. The forest file is an availability status, not forest geometry;
the Oshiwara river file is a reduced evidence sample; and the Bhote Koshi
centerline is event-specific and CC BY-NC 4.0. Steward approval, canonical
identifiers, MDU mapping, and applicable license review are prerequisites to
any separate canonical publication workflow. This importer does not promote
or approve candidates.
