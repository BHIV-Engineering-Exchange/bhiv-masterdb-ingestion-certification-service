# AISStream vessel-position ingestion

MASTERDB fetches AISStream only from the backend. The API key is read from
`AISSTREAM_API_KEY` through the existing `.env` loading in `main.py`; it is
never sent to clients or returned by an API.

## API

`POST /aisstream/ingest` opens a bounded AISStream subscription, normalizes
`PositionReport` messages, and stores the latest record for each MMSI.

```json
{
  "bounding_boxes": [[[25.835, -80.208], [25.603, -79.879]]],
  "max_messages": 25,
  "timeout_seconds": 15
}
```

`GET /aisstream/observations?limit=100&offset=0` returns stored positions.
Both endpoints require a MASTERDB bearer token. Bounding boxes are mandatory
to prevent an accidental global live subscription.

Records contain the MMSI (`vessel_id`), coordinates, speed over ground,
course over ground, AIS UTC-second timestamp, receipt timestamp, message type,
and provider metadata. Invalid JSON, non-position messages, missing or invalid
coordinates are skipped. A bounded reconnect loop retries failed WebSocket
connections. A repeated MMSI updates the existing record rather than creating
a duplicate.

The implementation uses `SqlArtifactStore` when `MASTERDB_DATABASE_URL` is
configured, in the `ais_observations` store partition. The local file-backed
JSON store remains the existing fallback for non-database development setups.

## Verification — 23 October 2026

An isolated MASTERDB server authenticated to AISStream with the configured
server-side environment value. A bounded subscription in the Miami example
area received two live `PositionReport` messages; both were normalized,
persisted to SQLite, and returned through `GET /aisstream/observations`. A
fresh process using the same database returned both stored records.

The existing `cap-maritime-cargo` capability and
`datasets/synthetic/maritime_vessels.json` remain demo/synthetic data. This
new observation API does not relabel that capability as live, and it does not
establish a canonical dataset or MDU write contract.
