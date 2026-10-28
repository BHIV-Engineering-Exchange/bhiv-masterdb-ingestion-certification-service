"""Read God's Eye View's static Bhote Koshi historical event pack."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


class BhoteKoshiSourceUnavailable(RuntimeError):
    """Raised when the configured source repository files are unavailable."""


def source_root() -> Path:
    configured = os.environ.get("GODS_EYE_VIEW_BHOTE_KOSHI_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "gods-eye-view"


def bundled_source_root() -> Path:
    """Return the repository-owned immutable source snapshot directory.

    CI and deployed MASTERDB instances do not have a sibling God's Eye View
    checkout.  These files are exact static snapshots, not generated event
    storage, and preserve the original source paths in the provenance payload.
    """
    return Path(__file__).resolve().parents[1] / "datasets" / "gods_eye_view" / "bhote_koshi"


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BhoteKoshiSourceUnavailable("God's Eye View Bhote Koshi source files are unavailable") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_source_coordinates(path: Path) -> list[list[float]]:
    text = _read(path).decode("utf-8-sig")
    expression = re.compile(
        r"Object\.freeze\(\[\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*"
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*\]\)"
    )
    points = [[float(lon), float(lat)] for lon, lat in expression.findall(text)]
    # One additional opener wraps the exported coordinate array itself.
    if not points or text.count("Object.freeze([") != len(points) + 1:
        raise ValueError("Bhote Koshi flood path source has an unsupported coordinate representation")
    return points


def _presentation_metadata(event_module: bytes) -> dict[str, Any]:
    text = event_module.decode("utf-8-sig")
    names = {
        "playback_seconds": "BHOTE_KOSHI_PLAYBACK_SECONDS",
        "prologue_end_ratio": "BHOTE_KOSHI_PROLOGUE_END",
        "corridor_end_ratio": "BHOTE_KOSHI_CORRIDOR_END",
        "camera_hold_ratio": "BHOTE_KOSHI_CAMERA_HOLD_RATIO",
    }
    values: dict[str, Any] = {}
    for key, constant in names.items():
        match = re.search(rf"export const {constant} = (\d+(?:\.\d+)?);", text)
        if not match:
            raise ValueError(f"Bhote Koshi event source is missing {constant}")
        value = float(match.group(1))
        values[key] = int(value) if value.is_integer() else value
    values["scene_presentation"] = "scene-beat"
    return values


def fetch_bhote_koshi_event() -> dict[str, Any]:
    """Load source JSON, source path coordinates, and provenance hashes."""
    root = source_root()
    relative_files = {
        "flood_path_module": Path("src/data/bhoteKoshiFloodPath.js"),
        "event_module": Path("src/data/bhoteKoshiEvent.js"),
        "embedded_media_module": Path("src/data/bhoteKoshiEmbeddedMedia.js"),
        # bhoteKoshiEvent.js loads this runtime event pack; it contains the
        # actual event narrative, evidence timeline, geometry references, and
        # third-party media-link metadata.
        "event_pack": Path("public/events/bhote-koshi-2026/event.json"),
    }
    source_paths = {key: root / relative for key, relative in relative_files.items()}
    # A configured root is an explicit deployment choice and must fail loudly
    # when incomplete.  Otherwise use the checked-in static source snapshot
    # when the sibling development checkout is unavailable.
    if not all(path.is_file() for path in source_paths.values()) and not os.environ.get(
        "GODS_EYE_VIEW_BHOTE_KOSHI_ROOT"
    ):
        bundled = bundled_source_root()
        source_paths = {
            "flood_path_module": bundled / "bhoteKoshiFloodPath.js",
            "event_module": bundled / "bhoteKoshiEvent.js",
            "embedded_media_module": bundled / "bhoteKoshiEmbeddedMedia.js",
            "event_pack": bundled / "event.json",
        }
    raw_files = {key: _read(path) for key, path in source_paths.items()}
    try:
        event = json.loads(raw_files["event_pack"].decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Bhote Koshi event pack is not valid UTF-8 JSON") from exc

    return {
        "source": "God's Eye View / GeoPera / Vantor Open Data",
        "data_mode": "STATIC_HISTORICAL_RECONSTRUCTION",
        "event": event,
        "flood_path_coordinates": _read_source_coordinates(source_paths["flood_path_module"]),
        "presentation_metadata": _presentation_metadata(raw_files["event_module"]),
        "source_files": [
            {
                "role": key,
                "path": relative.as_posix(),
                "sha256": _sha256(raw_files[key]),
            }
            for key, relative in relative_files.items()
        ],
        "path_source_url": "https://github.com/geo-pera/bhotekoshi-2026-reconstruction/blob/main/vectors/river_centerline.geojson",
        "path_license": "CC BY-NC 4.0",
        "attribution": "Imagery: Vantor Open Data; reconstruction: GeoPera (CC BY-NC 4.0). Linked witness posts and the GeoGeorgeShadrach geolocation map retain their owners' terms.",
        "media_mode": "EXTERNAL_LINK_METADATA_ONLY",
    }
