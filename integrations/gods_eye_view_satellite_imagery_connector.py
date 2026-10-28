"""Safe manifest and live probe for God's Eye View's satellite basemap stack.

Imagery stays provider hosted. Verification fetches one real tile and stores
only sanitized service metadata in the source registry.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

ESRI_TILE_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/0/0/0"
OSM_TILE_URL = "https://tile.openstreetmap.org/0/0/0.png"
ION_ENDPOINT_URL = "https://api.cesium.com/v1/assets/2/endpoint"
TIMEOUT_SECONDS = 15
MAX_TILE_BYTES = 256 * 1024
ATTRIBUTION = "Powered by Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community; fallback © OpenStreetMap contributors. Cesium ion attribution applies when ion imagery is used."


def _ion_token() -> str | None:
    token = os.environ.get("CESIUM_ION_TOKEN", "").strip()
    return token or None


def safe_manifest(verification: dict[str, Any] | None = None) -> dict[str, Any]:
    result = verification or {}
    return {
        "dataset_id": "gods_eye_view_world_satellite_imagery",
        "service_type": "WORLD_SATELLITE_IMAGERY",
        "status": result.get("status", "CONFIGURED"),
        "provider": "Esri World Imagery; Cesium ion imagery fallback when configured; OpenStreetMap fallback",
        "source_module": "God's Eye View src/maps/imagery.js",
        "preferred_provider": "Esri World Imagery",
        "fallback_providers": ["Cesium ion imagery (AERIAL)", "OpenStreetMap Standard Tiles"],
        "cesium_ion_token_configured": bool(_ion_token()),
        "credential_values_included": False,
        "endpoints": {
            "esri": "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer",
            "cesium_ion": ION_ENDPOINT_URL if _ion_token() else None,
            "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        },
        "coverage": "Global; imagery availability and resolution vary by location and provider.",
        "attribution": ATTRIBUTION,
        "data_mode": "EXTERNAL_GEOPATIAL_TILE_SERVICE",
        "storage_mode": "Tile payloads are not stored as observation rows.",
        "last_verification": {key: result[key] for key in ("status", "provider", "verified_at_utc", "tile_http_status", "tile_content_type", "tile_bytes", "tiles_loaded", "reason") if key in result},
    }


def _fetch_tile(url: str, provider: str) -> dict[str, Any]:
    response = requests.get(url, timeout=TIMEOUT_SECONDS, headers={"User-Agent": "BHIV-MASTERDB/1.0 (satellite imagery service verification)"}, stream=True)
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            raise ValueError("provider_non_image_response")
        size = 0
        for chunk in response.iter_content(chunk_size=16384):
            size += len(chunk)
            if size >= MAX_TILE_BYTES:
                size = MAX_TILE_BYTES
                break
        if size == 0:
            raise ValueError("provider_empty_tile")
        return {"status": "LIVE_VERIFIED", "provider": provider, "tile_http_status": response.status_code, "tile_content_type": content_type, "tile_bytes": size, "tiles_loaded": True, "verified_at_utc": datetime.now(timezone.utc).isoformat()}
    finally:
        response.close()


def verify_satellite_imagery() -> dict[str, Any]:
    """Try real Esri, optional ion AERIAL, then OSM tiles; expose no secrets."""
    attempts: list[dict[str, str]] = []
    for name, url in (("esri_world_imagery", ESRI_TILE_URL), ("cesium_ion_aerial", None), ("openstreetmap", OSM_TILE_URL)):
        if name == "cesium_ion_aerial":
            token = _ion_token()
            if not token:
                continue
            try:
                endpoint = requests.get(ION_ENDPOINT_URL, params={"access_token": token}, timeout=TIMEOUT_SECONDS)
                endpoint.raise_for_status()
                data = endpoint.json()
                endpoint.close()
                url = data.get("url") if isinstance(data, dict) else None
                if not isinstance(url, str):
                    raise ValueError("ion_endpoint_unavailable")
                name = "cesium_ion_aerial"
            except (requests.RequestException, ValueError, TypeError):
                attempts.append({"provider": name, "status": "UNAVAILABLE", "reason": "ion_endpoint_unavailable"})
                continue
        try:
            result = _fetch_tile(url, name)
            result["attempts"] = attempts + [{"provider": name, "status": "LIVE_VERIFIED"}]
            return result
        except (requests.RequestException, ValueError):
            attempts.append({"provider": name, "status": "UNAVAILABLE", "reason": "provider_tile_unavailable"})
    return {"status": "UNAVAILABLE", "reason": "all_provider_tiles_unavailable", "tiles_loaded": False, "credential_values_included": False, "attempts": attempts}
