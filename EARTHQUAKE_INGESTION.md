# USGS earthquake observations

MASTERDB now has a dedicated observation path for the existing GEV dataset
`ds-gev-seismic-events` and capability `cap-gev-earthquake-monitoring`.

## API

All routes require a MASTERDB bearer token (`POST /auth/token`). Trigger a live
USGS daily-feed fetch and idempotent upsert:

```http
POST /earthquakes/usgs/ingest
Authorization: Bearer <token>
```

The response reports fetched, inserted, and updated counts. Re-fetches use the
USGS `event_id` as their key; an existing event is replaced with the latest
feed values. A batch is fully validated before any event is written.

Retrieve observations, newest first:

```http
GET /earthquakes/usgs/observations?limit=100&offset=0
Authorization: Bearer <token>
```

Open `/earthquakes/map` for a Leaflet map and table backed by that read API.
Provide the API base URL and a bearer token in the page. The view shows event
ID, place, magnitude, depth, event time, coordinates, and source link.

## Persistence

When `MASTERDB_DATABASE_URL` is configured, observations use the existing
`SqlArtifactStore` architecture, in its own `earthquake_observations` store
partition and keyed by event ID. Otherwise they use the existing JSON
`ArtifactStore` under `MASTERDB_STORAGE_DIR/earthquake_observations`, or the
default `earthquake_observation_store` directory. SQLite file URLs can be used
for a local persistent database. Process-memory-only persistence is not used
for this service.

## MDU status and limitations

`MDU_INTERFACE_CONTRACT.md` remains draft and documents only MDU GET methods.
It explicitly says field semantics are pending joint sign-off. No approved
MDU observation write endpoint, payload schema, or write authorization
contract is present in this repository. Therefore MASTERDB does not send
earthquake writes to MDU; that integration remains pending contract
confirmation. The configured-read status endpoint does not by itself prove
earthquake schema compatibility or write access.

The repository has no pre-existing product frontend framework. The included
standalone map is a thin API client, not a deployment of a full GEV frontend.
It needs browser access to MASTERDB and the Leaflet/OpenStreetMap tile hosts.
The repository tests prove local fetch-route wiring with a stubbed USGS
response, storage behavior, duplicate updates, validation, and SQLite restart
persistence. They do not prove external USGS availability, deployed database
configuration, browser connectivity, or live MDU integration.

## Local live verification — 23 October 2026

An isolated local MASTERDB process was run with a file-backed SQLite database
and valid bearer-token authentication. `POST /earthquakes/usgs/ingest`
retrieved and inserted 270 records from the live USGS daily GeoJSON feed.
`GET /earthquakes/usgs/observations?limit=1000` returned the stored records.
A fresh MASTERDB process, pointed at the same SQLite file, returned all 270
records after restart.

The map route returned HTTP 200 and its client contains the Leaflet marker and
table rendering path against the stored-observation API. The page was opened
locally for visual checking; it requires a bearer token to load data. Visual
marker rendering therefore still needs confirmation in a browser with that
token entered. This local evidence does not establish the configuration or
availability of a deployed target environment.

During live verification, USGS returned a valid event with negative depth.
The observation validator now accepts finite numeric depths, preserving the
value USGS supplies instead of rejecting the whole atomic batch.
