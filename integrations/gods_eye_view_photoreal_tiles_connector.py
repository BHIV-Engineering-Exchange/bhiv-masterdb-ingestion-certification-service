"""Safe manifest and live probes for God's Eye View's Google 3D Tiles stack.

Secrets are resolved on the server and never included in returned metadata or
exception text. Photorealistic tiles remain an external geospatial service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from dotenv import dotenv_values


GOOGLE_ROOT_URL = "https://tile.googleapis.com/v1/3dtiles/root.json"
ION_ENDPOINT_URL = "https://api.cesium.com/v1/assets/2275207/endpoint"
ION_ASSET_ID = 2275207
REQUEST_TIMEOUT_SECONDS = 15
MAX_TILE_BYTES = 256 * 1024


class PhotorealTilesConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderCredentials:
    # Keep this object private to the integration layer. Do not repr/log it.
    google_api_key: str | None = field(repr=False)
    cesium_ion_token: str | None = field(repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.google_api_key or self.cesium_ion_token)

    @property
    def preferred_route(self) -> str | None:
        if self.google_api_key:
            return "google-direct"
        if self.cesium_ion_token:
            return "google-ion"
        return None


def source_root() -> Path:
    configured = os.environ.get("GODS_EYE_VIEW_SOURCE_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "gods-eye-view"


def _dotenv_credentials(root: Path) -> dict[str, str]:
    # Match Vite's default development-mode file precedence; process env wins.
    mode = (os.environ.get("MODE") or "development").strip()
    filenames = (f".env.{mode}.local", f".env.{mode}", ".env.local", ".env")
    values: dict[str, str] = {}
    for name in reversed(filenames):
        path = root / name
        if path.is_file():
            values.update({k: str(v).strip() for k, v in dotenv_values(path).items() if v is not None})
    return values


def resolve_credentials() -> ProviderCredentials:
    values = _dotenv_credentials(source_root())
    google_key = os.environ.get("GOOGLE_MAPS_API_KEY") or values.get("GOOGLE_MAPS_API_KEY")
    ion_token = os.environ.get("CESIUM_ION_TOKEN") or values.get("CESIUM_ION_TOKEN")
    return ProviderCredentials(
        google_api_key=google_key.strip() if isinstance(google_key, str) and google_key.strip() else None,
        cesium_ion_token=ion_token.strip() if isinstance(ion_token, str) and ion_token.strip() else None,
    )


def safe_manifest(verification: dict[str, Any] | None = None) -> dict[str, Any]:
    credentials = resolve_credentials()
    route = credentials.preferred_route
    last_verification = verification or {}
    status = (
        "LIVE_VERIFIED" if last_verification.get("status") == "LIVE_VERIFIED" and credentials.configured
        else "UNAVAILABLE" if last_verification.get("status") == "UNAVAILABLE"
        else "CONFIGURED" if credentials.configured
        else "UNAVAILABLE"
    )
    return {
        "dataset_id": "google_cesium_photorealistic_3d_tiles",
        "service_type": "PHOTOREALISTIC_3D_TILES",
        "status": status,
        "provider": "Google Maps Platform Photorealistic 3D Tiles via CesiumJS",
        "loader": "God's Eye View src/maps/google3d.js",
        "preferred_route": route,
        "fallback_route": "google-ion" if credentials.google_api_key and credentials.cesium_ion_token else None,
        "credential_configured": credentials.configured,
        "credential_values_included": False,
        "google_direct_root_endpoint": GOOGLE_ROOT_URL,
        "cesium_ion_endpoint": ION_ENDPOINT_URL if credentials.cesium_ion_token else None,
        "cesium_ion_asset_id": ION_ASSET_ID,
        "resolved_tileset_url_included": False,
        "coverage": "Global where Google Photorealistic 3D coverage is available; completeness varies by location.",
        "attribution": "Google Maps Platform per-tile credits must remain visible; Cesium ion attribution applies on the hosted asset route.",
        "storage_mode": "EXTERNAL_GEOPATIAL_SERVICE; tile payloads are not stored as observation records.",
        "last_verification": {
            key: last_verification[key]
            for key in ("status", "verified_at_utc", "route", "root_content_type", "root_asset_version", "tile_content_type", "tile_bytes", "tiles_loaded", "credential_configured", "reason", "attempts")
            if key in last_verification
        },
    }


def _root_json(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("root"), dict) or not isinstance(payload.get("asset"), dict):
        raise PhotorealTilesConfigurationError("Provider response was not a 3D Tiles tileset manifest")
    return payload


def _content_uris(root_tile: dict[str, Any], *, limit: int = 32) -> list[str]:
    found: list[str] = []
    pending = [(root_tile, 0)]
    visited = 0
    while pending and visited < limit:
        tile, depth = pending.pop(0)
        visited += 1
        content = tile.get("content")
        contents = tile.get("contents")
        candidates = ([content] if isinstance(content, dict) else [])
        if isinstance(contents, list):
            candidates.extend(item for item in contents if isinstance(item, dict))
        for item in candidates:
            uri = item.get("uri") or item.get("url")
            if isinstance(uri, str) and uri:
                sampled = (uri.replace("{level}", "0").replace("{x}", "0")
                           .replace("{y}", "0").replace("{z}", "0"))
                if "{" not in sampled:
                    found.append(sampled)
        children = tile.get("children")
        if depth < 3 and isinstance(children, list):
            pending.extend((child, depth + 1) for child in children if isinstance(child, dict))
    return found


def _fetch_root_and_tile(route: str, credentials: ProviderCredentials) -> dict[str, Any]:
    session = requests.Session()
    try:
        if route == "google-direct":
            key = credentials.google_api_key
            if not key:
                raise PhotorealTilesConfigurationError("Direct Google route is not configured")
            root_response = session.get(
                GOOGLE_ROOT_URL, params={"key": key}, timeout=REQUEST_TIMEOUT_SECONDS,
            )
            tileset = _root_json(root_response)
            content_urls = _content_uris(tileset["root"])
            tile_response = None
            for uri in content_urls:
                if len(uri) > 2048:
                    continue
                candidate = session.get(
                    urljoin(root_response.url, uri), params={"key": key},
                    timeout=REQUEST_TIMEOUT_SECONDS, stream=True,
                )
                if candidate.ok and candidate.headers.get("Content-Type", "").split(";", 1)[0].lower() not in ("application/json", "text/json"):
                    tile_response = candidate
                    break
                candidate.close()
            if tile_response is None:
                raise PhotorealTilesConfigurationError("Provider tileset manifest had no fetchable renderable tile")
        elif route == "google-ion":
            token = credentials.cesium_ion_token
            if not token:
                raise PhotorealTilesConfigurationError("Cesium ion route is not configured")
            endpoint_response = session.get(
                ION_ENDPOINT_URL,
                # Match CesiumJS IonResource.fromAssetId: endpoint discovery
                # sends access_token as a query parameter, then the returned
                # asset access token is used as a bearer token for asset URLs.
                params={"access_token": token},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            endpoint_response.raise_for_status()
            endpoint = endpoint_response.json()
            if not isinstance(endpoint, dict) or not isinstance(endpoint.get("url"), str):
                raise PhotorealTilesConfigurationError("Cesium ion did not return an authorized asset endpoint")
            asset_token = endpoint.get("accessToken") or token
            headers = {"Authorization": f"Bearer {asset_token}"}
            root_response = session.get(endpoint["url"], headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            tileset = _root_json(root_response)
            content_urls = _content_uris(tileset["root"])
            tile_response = None
            for uri in content_urls:
                if len(uri) > 2048:
                    continue
                candidate = session.get(
                    urljoin(root_response.url, uri), headers=headers,
                    timeout=REQUEST_TIMEOUT_SECONDS, stream=True,
                )
                if candidate.ok and candidate.headers.get("Content-Type", "").split(";", 1)[0].lower() not in ("application/json", "text/json"):
                    tile_response = candidate
                    break
                candidate.close()
            if tile_response is None:
                raise PhotorealTilesConfigurationError("Provider tileset manifest had no fetchable renderable tile")
        else:
            raise PhotorealTilesConfigurationError("No photorealistic tiles route is configured")

        tile_bytes = 0
        for chunk in tile_response.iter_content(chunk_size=16 * 1024):
            tile_bytes += len(chunk)
            if tile_bytes >= MAX_TILE_BYTES:
                tile_bytes = MAX_TILE_BYTES
                break
        if tile_bytes == 0:
            raise PhotorealTilesConfigurationError("Provider returned an empty tile payload")
        result = {
            "status": "LIVE_VERIFIED",
            "route": route,
            "root_http_status": root_response.status_code,
            "root_content_type": root_response.headers.get("Content-Type", "").split(";", 1)[0],
            "root_asset_version": tileset["asset"].get("version"),
            "tile_http_status": tile_response.status_code,
            "tile_content_type": tile_response.headers.get("Content-Type", "").split(";", 1)[0],
            "tile_bytes": tile_bytes,
        }
        tile_response.close()
        return result
    except PhotorealTilesConfigurationError:
        raise
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        reason = "provider_rejected_credentials" if status_code in (401, 403) else "provider_http_error"
        raise PhotorealTilesConfigurationError(reason) from None
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise PhotorealTilesConfigurationError("provider_tiles_unavailable_or_invalid") from None
    finally:
        session.close()


def verify_photoreal_tiles() -> dict[str, Any]:
    """Fetch a real tileset root and a tile payload; return sanitized metadata only."""
    credentials = resolve_credentials()
    routes = []
    if credentials.google_api_key:
        routes.append("google-direct")
    if credentials.cesium_ion_token:
        routes.append("google-ion")
    if not routes:
        return {
            "status": "UNAVAILABLE",
            "reason": "provider_credentials_not_configured",
            "credential_configured": False,
            "tiles_loaded": False,
        }

    attempts: list[dict[str, str]] = []
    for route in routes:
        try:
            result = _fetch_root_and_tile(route, credentials)
            result["credential_configured"] = True
            result["tiles_loaded"] = True
            result["attempts"] = attempts + [{"route": route, "status": "LIVE_VERIFIED"}]
            return result
        except PhotorealTilesConfigurationError as exc:
            attempts.append({"route": route, "status": "UNAVAILABLE", "reason": str(exc)})
    # Only sanitized reason codes are returned. Provider URLs, headers, and
    # response bodies (which may contain credentials) are never exposed.
    return {
        "status": "UNAVAILABLE",
        "reason": attempts[-1]["reason"] if attempts else "provider_tiles_unavailable_or_invalid",
        "attempts": attempts,
        "credential_configured": True,
        "tiles_loaded": False,
    }
