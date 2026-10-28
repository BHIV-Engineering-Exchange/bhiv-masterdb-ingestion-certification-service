"""Securely validate and install a replacement TomTom key, then ingest one tile.

Run from the repository root with `python scripts/replace_tomtom_key.py`.
The key is prompted without terminal echo, is never accepted as a CLI argument,
and is written to the ignored .env only after a successful real TomTom response.
"""
from datetime import datetime, timezone
from getpass import getpass
import os
from pathlib import Path
import sys

from dotenv import load_dotenv, set_key


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"
VERIFY_TILE = {"z": 12, "x": 1204, "y": 1540}


def main() -> int:
    if not ENV_FILE.is_file():
        print("Cannot install a key: repository .env file is missing.", file=sys.stderr)
        return 2

    load_dotenv(ENV_FILE)
    candidate = getpass("Replacement TomTom API key (input hidden): ").strip()
    if not candidate:
        print("No key entered; configuration was not changed.", file=sys.stderr)
        return 2

    # Import the application only after dotenv initialization. The candidate
    # stays in process memory until TomTom accepts it.
    import main as app
    from integrations.tomtom_traffic_connector import fetch_flow_tiles

    os.environ["TOMTOM_API_KEY"] = candidate
    try:
        feed = fetch_flow_tiles([VERIFY_TILE])
    except Exception as exc:
        # Connector exceptions contain only sanitized status text, never URLs.
        print(f"TomTom key validation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    # Persist only an accepted credential. `set_key` updates the ignored .env
    # file without sending or printing the secret elsewhere.
    written, _ = set_key(str(ENV_FILE), "TOMTOM_API_KEY", candidate, quote_mode="always")
    if not written:
        print("TomTom accepted the key, but .env could not be updated.", file=sys.stderr)
        return 3

    result = app.traffic_observation_service.ingest(feed)
    verified_at = datetime.now(timezone.utc).isoformat()
    tiles = [{"z": t["z"], "x": t["x"], "y": t["y"]} for t in feed["tiles"]]
    app.source_registry_service.mark_validated(
        "src-gev-tomtom-traffic", verified_at,
        {"last_verified_tiles": tiles, "last_verified_segment_count": feed["record_count"], "last_fetch_status": "LIVE_VERIFIED"},
    )
    app.traffic_last_verified_at = verified_at
    app.traffic_verified_tiles = tiles
    app.traffic_last_fetch_error = False
    print(f"TomTom key accepted. Stored {result['inserted']} new and {result['updated']} updated live segments from {feed['tile_count']} tile(s).")
    print("Restart MASTERDB, then use POST /traffic/tomtom/ingest for additional tiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
