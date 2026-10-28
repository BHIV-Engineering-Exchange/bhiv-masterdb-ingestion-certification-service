# ADS-B military-feed observations

MASTERDB retrieves publicly broadcast ADS-B observations from
`https://api.adsb.lol/v2/mil`. These records represent aircraft present in
that public feed; they do not establish identity, affiliation, operational
intent, or complete coverage.

## API

`POST /aircraft/adsb/military/ingest` fetches the current feed and persists
valid coordinate-bearing records. `GET /aircraft/adsb/military/observations`
returns stored observations. Both require a MASTERDB bearer token.

Each record includes ICAO hex identifier, callsign when broadcast, coordinates,
barometric altitude when numeric, ground speed, track, provider observation
time when available, provider URL, and selected metadata. Missing optional
fields remain absent. Records missing usable coordinates are skipped.

Storage uses the existing `SqlArtifactStore` under the
`aircraft_observations` partition when `MASTERDB_DATABASE_URL` is configured.
The record key combines hex ID and observation time when the upstream time is
available, preserving distinct observations; re-ingesting the same key updates
that record. Rate-limit responses return HTTP 429 and other upstream failures
return HTTP 502.

## Local live verification — 23 October 2026

An isolated MASTERDB process used a file-backed SQLite database and valid
bearer-token authentication. `POST /aircraft/adsb/military/ingest` retrieved
83 coordinate-bearing records from the live upstream response and inserted all
83. `GET /aircraft/adsb/military/observations` returned stored records,
including hex ID, position, kinematics, upstream timestamp, and provenance.

This proves local transport and persistence for the current public feed. It
does not establish complete coverage, affiliation, operational intent, or a
canonical capability registration.
