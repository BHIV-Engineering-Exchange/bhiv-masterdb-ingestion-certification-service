"""Safe provider manifest and live tile probe for God's Eye View terrain."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any
from urllib.parse import urljoin

import requests

RE_URL = "https://terrain.reearth.land/cesium-mesh/ellipsoid"
RE_LAYER_URL = f"{RE_URL}/layer.json"
ION_ASSET_ID = 1
ION_ENDPOINT_URL = f"https://api.cesium.com/v1/assets/{ION_ASSET_ID}/endpoint"
TIMEOUT_SECONDS = 20
MAX_TILE_BYTES = 512 * 1024
RE_ATTRIBUTION = "Terrain (keyless globe stacks): Re:Earth Terrain / Mapterhorn (CC BY 4.0) / EGM2008 (NGA)."


def _ion_token() -> str | None:
    token = os.environ.get("CESIUM_ION_TOKEN", "").strip()
    return token or None


def safe_manifest(verification: dict[str, Any] | None = None) -> dict[str, Any]:
    ion_enabled = bool(_ion_token())
    last = verification or {}
    return {
        "dataset_id": "gods_eye_view_world_3d_terrain",
        "service_type": "QUANTIZED_MESH_TERRAIN",
        "status": last.get("status", "CONFIGURED"),
        "provider": "Cesium World Terrain via Cesium ion" if ion_enabled else "Re:Earth Terrain / Mapterhorn",
        "source_module": "God's Eye View src/maps/terrain.js",
        "provider_selection": "CESIUM_ION_ASSET_1" if ion_enabled else "KEYLESS_REEARTH_QUANTIZED_MESH",
        "fallback": "Cesium EllipsoidTerrainProvider (flat ellipsoid; no terrain tiles) if keyless terrain initialization fails",
        "coverage": "Provider-defined coverage; terrain service metadata is authoritative.",
        "attribution": "Cesium ion attribution is required and supplied by CesiumJS when the ion asset is active." if ion_enabled else RE_ATTRIBUTION,
        "license": "Cesium ion terms and asset attribution apply." if ion_enabled else "Terrain mesh: CC BY 4.0; geoid: EGM2008 (NGA, public domain).",
        "endpoints": {
            "reearth_layer": RE_LAYER_URL,
            "cesium_ion_asset_id": ION_ASSET_ID if ion_enabled else None,
            "cesium_ion_endpoint": ION_ENDPOINT_URL if ion_enabled else None,
        },
        "credential_configured": ion_enabled,
        "credential_values_included": False,
        "data_mode": "EXTERNAL_GEOPATIAL_TERRAIN_SERVICE",
        "storage_mode": "Terrain metadata only; terrain tiles are not stored as observation records.",
        "last_verification": {key: last[key] for key in ("status", "provider", "verified_at_utc", "layer_http_status", "tile_http_status", "tile_content_type", "tile_bytes", "tiles_loaded", "reason") if key in last},
    }


def _read_limited(response: requests.Response) -> int:
    size = 0
    for chunk in response.iter_content(chunk_size=16 * 1024):
        size += len(chunk)
        if size >= MAX_TILE_BYTES:
            return MAX_TILE_BYTES
    if size == 0:
        raise ValueError("provider_empty_tile")
    return size


def _validate_mesh_response(response: requests.Response) -> str:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if "quantized-mesh" not in content_type and content_type != "application/octet-stream":
        raise ValueError("provider_response_not_quantized_mesh")
    return content_type


def _fetch_reearth() -> dict[str, Any]:
    with requests.Session() as session:
        layer_response = session.get(RE_LAYER_URL, timeout=TIMEOUT_SECONDS)
        layer_response.raise_for_status()
        layer = layer_response.json()
        if not isinstance(layer, dict) or layer.get("format") != "quantized-mesh-1.0":
            raise ValueError("provider_terrain_metadata_invalid")
        templates = layer.get("tiles")
        if not isinstance(templates, list) or not templates or not isinstance(templates[0], str):
            raise ValueError("provider_terrain_metadata_invalid")
        tile_path = templates[0].replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")
        if "{version}" in tile_path and layer.get("version") is not None:
            tile_path = tile_path.replace("{version}", str(layer["version"]))
        if "{" in tile_path:
            raise ValueError("provider_terrain_template_unsupported")
        tile_url = urljoin(RE_URL.rstrip("/") + "/", tile_path)
        tile_response = session.get(tile_url, timeout=TIMEOUT_SECONDS, stream=True)
        try:
            tile_response.raise_for_status()
            content_type = _validate_mesh_response(tile_response)
            size = _read_limited(tile_response)
            return {
                "status": "LIVE_VERIFIED", "provider": "reearth_mapterhorn",
                "layer_http_status": layer_response.status_code,
                "tile_http_status": tile_response.status_code,
                "tile_content_type": content_type,
                "tile_bytes": size,
                "tiles_loaded": True,
                "format": layer.get("format"),
                "tile_template": templates[0],
                "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            tile_response.close()


def _fetch_ion() -> dict[str, Any]:
    token = _ion_token()
    if not token:
        raise ValueError("ion_token_not_configured")
    with requests.Session() as session:
        endpoint_response = session.get(ION_ENDPOINT_URL, params={"access_token": token}, timeout=TIMEOUT_SECONDS)
        endpoint_response.raise_for_status()
        endpoint = endpoint_response.json()
        if not isinstance(endpoint, dict) or endpoint.get("type") != "TERRAIN" or not isinstance(endpoint.get("url"), str):
            raise ValueError("ion_terrain_endpoint_invalid")
        access_token = endpoint.get("accessToken") or token
        headers = {"Authorization": f"Bearer {access_token}"}
        layer_url = urljoin(endpoint["url"].rstrip("/") + "/", "layer.json")
        layer_response = session.get(layer_url, headers=headers, timeout=TIMEOUT_SECONDS)
        layer_response.raise_for_status()
        layer = layer_response.json()
        if not isinstance(layer, dict) or layer.get("format") != "quantized-mesh-1.0":
            raise ValueError("ion_terrain_metadata_invalid")
        templates = layer.get("tiles")
        if not isinstance(templates, list) or not templates or not isinstance(templates[0], str):
            raise ValueError("ion_terrain_metadata_invalid")
        path = templates[0].replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")
        if "{version}" in path and layer.get("version") is not None:
            path = path.replace("{version}", str(layer["version"]))
        if "{" in path:
            raise ValueError("ion_terrain_template_unsupported")
        tile_response = session.get(urljoin(layer_url, path), headers=headers, timeout=TIMEOUT_SECONDS, stream=True)
        try:
            tile_response.raise_for_status()
            content_type = _validate_mesh_response(tile_response)
            size = _read_limited(tile_response)
            return {
                "status": "LIVE_VERIFIED", "provider": "cesium_ion_world_terrain",
                "layer_http_status": layer_response.status_code,
                "tile_http_status": tile_response.status_code,
                "tile_content_type": content_type,
                "tile_bytes": size, "tiles_loaded": True,
                "format": layer.get("format"), "tile_template": templates[0],
                "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        finally:
            tile_response.close()


def verify_world_terrain() -> dict[str, Any]:
    """Fetch the selected provider's layer metadata and a real terrain tile."""
    try:
        result = _fetch_ion() if _ion_token() else _fetch_reearth()
        result["credential_configured"] = bool(_ion_token())
        result["credential_values_included"] = False
        return result
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else None
        reason = "provider_rejected_credentials" if code in (401, 403) else "provider_http_error"
    except requests.RequestException:
        reason = "provider_unreachable"
    except (ValueError, TypeError, KeyError):
        reason = "provider_terrain_metadata_invalid_or_unavailable"
    return {
        "status": "UNAVAILABLE", "reason": reason, "tiles_loaded": False,
        "provider": "cesium_ion_world_terrain" if _ion_token() else "reearth_mapterhorn",
        "credential_configured": bool(_ion_token()), "credential_values_included": False,
    }
