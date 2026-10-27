"""Read the static dams snapshot bundled with God's Eye View.

This is deliberately a file-backed connector: the upstream is a published,
static OSM/OpenInfraMap-derived snapshot, not a live API.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class DamsSourceUnavailable(RuntimeError):
    """Raised when the configured God's Eye View dams snapshot is missing."""


def dams_source_path() -> Path:
    configured = os.environ.get("GODS_EYE_VIEW_DAMS_PATH")
    if configured:
        return Path(configured).expanduser()
    return (
        Path(__file__).resolve().parents[2]
        / "gods-eye-view"
        / "src"
        / "data"
        / "local_data"
        / "dams"
        / "dams.geojsonl"
    )


def fetch_dams() -> dict[str, Any]:
    """Parse the actual bundled GeoJSONL snapshot without transforming fields."""
    path = dams_source_path()
    if not path.is_file():
        raise DamsSourceUnavailable("God's Eye View dams.geojsonl source file is unavailable")

    features: list[Any] = []
    parse_errors = 0
    try:
        with path.open("r", encoding="utf-8-sig") as source:
            for line in source:
                if not line.strip():
                    continue
                try:
                    features.append(json.loads(line))
                except json.JSONDecodeError:
                    parse_errors += 1
    except OSError as exc:
        raise DamsSourceUnavailable("God's Eye View dams source could not be read") from exc

    return {
        "source": "God's Eye View / OpenInfraMap",
        "source_path": "src/data/local_data/dams/dams.geojsonl",
        "source_format": "GeoJSONL",
        "data_mode": "STATIC_SNAPSHOT",
        "license": "Open Database License (ODbL) 1.0",
        "attribution": "© OpenStreetMap contributors; Open Infrastructure Map",
        "features": features,
        "parse_errors": parse_errors,
        "source_feature_count": len(features) + parse_errors,
    }
