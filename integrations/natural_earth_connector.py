"""Load the two bundled Natural Earth physical-region source snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


DATASETS = {
    "regions": "regions.json",
    "marine": "marine.json",
}
GEV_SOURCE_PATH = "src/data/local_data/natural_earth"
GEV_REPOSITORY = "https://github.com/bilawalsidhu/gods-eye-view"


class NaturalEarthSourceUnavailable(RuntimeError):
    """Raised when a bundled Natural Earth source snapshot cannot be read."""


def source_root() -> Path:
    configured = os.environ.get("GODS_EYE_VIEW_NATURAL_EARTH_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "datasets" / "natural_earth"


def source_path(dataset: str) -> Path:
    filename = DATASETS.get(dataset)
    if filename is None:
        raise ValueError("Unknown Natural Earth dataset")
    return source_root() / filename


def load_natural_earth_source(dataset: str) -> dict[str, Any]:
    """Load original source attributes and curation metadata without reshaping."""
    path = source_path(dataset)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NaturalEarthSourceUnavailable(f"Natural Earth {dataset} source file is unavailable") from exc
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NaturalEarthSourceUnavailable(f"Natural Earth {dataset} source file is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise NaturalEarthSourceUnavailable(f"Natural Earth {dataset} source root must be an object")
    return {
        "dataset": dataset,
        "source_file": path.name,
        "source_relative_path": f"{GEV_SOURCE_PATH}/{path.name}",
        "source_repository": GEV_REPOSITORY,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "feed": payload,
    }
