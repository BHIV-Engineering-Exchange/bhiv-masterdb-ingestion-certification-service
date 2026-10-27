"""Safe OpenFreeMap TileJSON and real vector-tile probe for God's Eye View."""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

TILEJSON_URL = "https://tiles.openfreemap.org/planet"
TIMEOUT_SECONDS = 20
MAX_TILE_BYTES = 2 * 1024 * 1024
EXPECTED_VECTOR_LAYERS = ("transportation", "landuse")


def _plain_attribution(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", value))).strip()


def _template_tile_url(tilejson: dict[str, Any]) -> str:
    templates = tilejson.get("tiles")
    if not isinstance(templates, list) or not templates or not isinstance(templates[0], str):
        raise ValueError("tilejson_missing_tile_template")
    template = templates[0]
    tile_url = template.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")
    if "{" in tile_url or "}" in tile_url:
        raise ValueError("tile_template_has_unsupported_placeholders")
    resolved = urljoin(TILEJSON_URL, tile_url)
    configured_origin = urlsplit(TILEJSON_URL)
    tile_origin = urlsplit(resolved)
    if (tile_origin.scheme, tile_origin.netloc) != (configured_origin.scheme, configured_origin.netloc):
        raise ValueError("tile_template_origin_mismatch")
    return resolved


def safe_manifest(verification: dict[str, Any] | None = None) -> dict[str, Any]:
    result = verification or {}
    return {
        "dataset_id": "gods_eye_view_openfreemap_vector_basemap",
        "service_type": "MAPBOX_VECTOR_TILES",
        "status": result.get("status", "CONFIGURED"),
        "provider": "OpenFreeMap / OpenMapTiles",
        "source_module": "God's Eye View src/sources/openFreeMap.js",
        "tilejson_endpoint": TILEJSON_URL,
        "tile_url_template": result.get("tile_url_template"),
        "style": "God's Eye View consumes TileJSON vector data; its source code does not select a cartographic style URL. It decodes transportation and landuse vector layers.",
        "vector_layers": result.get("vector_layers", list(EXPECTED_VECTOR_LAYERS)),
        "coverage": {
            "bounds": result.get("bounds"),
            "minzoom": result.get("minzoom"),
            "maxzoom": result.get("maxzoom"),
            "description": "Provider TileJSON coverage and zoom bounds; populated from the live service response.",
        },
        "attribution": result.get("attribution", "OpenFreeMap © OpenMapTiles; Data from OpenStreetMap"),
        "license": "OpenStreetMap data under ODbL 1.0; retain OpenFreeMap and OpenMapTiles attribution.",
        "fallback_workflow": "Street Traffic uses OpenFreeMap roads when TomTom is not configured; with TomTom, Hybrid uses OpenFreeMap for roads without TomTom flow. OpenFreeMap tile failures are reported and do not silently switch tile origins.",
        "data_mode": "EXTERNAL_GEOPATIAL_VECTOR_TILE_SERVICE",
        "storage_mode": "Tile payloads are not stored as observation records.",
        "credential_configured": False,
        "credential_values_included": False,
        "last_verification": {key: result[key] for key in ("status", "verified_at_utc", "tilejson_http_status", "tile_http_status", "tile_content_type", "tile_bytes", "vector_layers", "bounds", "minzoom", "maxzoom", "reason") if key in result},
    }


def verify_vector_basemap() -> dict[str, Any]:
    """Fetch the provider's TileJSON and one real vector tile at z/x/y 0/0/0."""
    try:
        with requests.Session() as session:
            metadata_response = session.get(
                TILEJSON_URL, timeout=TIMEOUT_SECONDS, allow_redirects=False,
                headers={"Accept": "application/json"},
            )
            metadata_response.raise_for_status()
            tilejson = metadata_response.json()
            if not isinstance(tilejson, dict) or tilejson.get("tilejson") != "3.0.0":
                raise ValueError("tilejson_metadata_invalid")
            if tilejson.get("name") != "OpenFreeMap":
                raise ValueError("unexpected_tilejson_provider")
            layer_rows = tilejson.get("vector_layers")
            if not isinstance(layer_rows, list):
                raise ValueError("tilejson_vector_layers_missing")
            layer_ids = [row.get("id") for row in layer_rows if isinstance(row, dict) and isinstance(row.get("id"), str)]
            if not any(layer in layer_ids for layer in EXPECTED_VECTOR_LAYERS):
                raise ValueError("expected_vector_layers_missing")
            tile_url = _template_tile_url(tilejson)
            tile_response = session.get(
                tile_url, timeout=TIMEOUT_SECONDS, allow_redirects=False,
                stream=True, headers={"Accept": "application/vnd.mapbox-vector-tile, application/x-protobuf, application/octet-stream"},
            )
            try:
                tile_response.raise_for_status()
                content_type = tile_response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if "json" in content_type or "text/html" in content_type:
                    raise ValueError("tile_response_not_vector_data")
                size = 0
                for chunk in tile_response.iter_content(chunk_size=16 * 1024):
                    size += len(chunk)
                    if size > MAX_TILE_BYTES:
                        raise ValueError("provider_vector_tile_exceeds_size_limit")
                if size == 0:
                    raise ValueError("provider_empty_vector_tile")
                attribution = _plain_attribution(tilejson.get("attribution"))
                return {
                    "status": "LIVE_VERIFIED",
                    "provider": "openfreemap_openmaptiles",
                    "tilejson_http_status": metadata_response.status_code,
                    "tile_http_status": tile_response.status_code,
                    "tile_content_type": content_type,
                    "tile_bytes": size,
                    "tile_url_template": tilejson["tiles"][0],
                    "tilejson_version": tilejson.get("version"),
                    "vector_layers": layer_ids,
                    "bounds": tilejson.get("bounds"),
                    "minzoom": tilejson.get("minzoom"),
                    "maxzoom": tilejson.get("maxzoom"),
                    "attribution": attribution or "OpenFreeMap © OpenMapTiles; Data from OpenStreetMap",
                    "tiles_loaded": True,
                    "credential_values_included": False,
                    "verified_at_utc": datetime.now(timezone.utc).isoformat(),
                }
            finally:
                tile_response.close()
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else None
        reason = "provider_http_error_" + str(code or "unknown")
    except requests.RequestException:
        reason = "provider_unreachable"
    except (ValueError, KeyError, TypeError):
        reason = "provider_metadata_or_tile_invalid"
    return {
        "status": "UNAVAILABLE", "provider": "openfreemap_openmaptiles",
        "reason": reason, "tiles_loaded": False,
        "credential_configured": False, "credential_values_included": False,
    }
