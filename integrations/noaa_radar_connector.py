"""Proxy the God’s Eye View nowCOAST radar manifest and raster responses."""
import math
import os
import re
import struct
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import requests


PRODUCT = "radar"
LAYER = "conus_base_reflectivity_mosaic"
PRODUCT_LAYERS = {
    "radar": LAYER,
    "clouds": "global_longwave_imagery_mosaic",
    "clouds-regional": "goes_longwave_imagery",
    "lightning": "ldn_lightning_strike_density",
}
PRODUCT_IMAGE_SIZES = {
    "radar": {"1024x512", "2048x1024", "4096x2048"},
    "clouds": {"1024x512", "2048x1024"},
    "clouds-regional": {"1024x512", "2048x1024", "4096x2048"},
    "lightning": {"1024x512", "2048x1024", "4096x2048"},
}
MAX_MANIFEST_BYTES = 512 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024
IMAGE_SIZES = {"1024x512", "2048x1024", "4096x2048"}
TILE_SIZES = {"256", "512", "1024"}


class RadarUpstreamError(RuntimeError):
    pass


class RadarRequestError(ValueError):
    pass


def _base_url() -> str:
    base = os.environ.get("GODS_EYE_VIEW_BASE_URL", "http://127.0.0.1:4173").strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise RadarUpstreamError("God’s Eye View weather provider is not configured")
    return base


def _validate_manifest(value: Any, product: str = PRODUCT) -> dict[str, Any]:
    if product not in PRODUCT_LAYERS or not isinstance(value, dict) or value.get("product") != product:
        raise RadarUpstreamError("God’s Eye View returned an invalid imagery manifest")
    if value.get("unavailable") or not isinstance(value.get("times"), list) or not value["times"]:
        raise RadarUpstreamError("NOAA nowCOAST radar metadata is unavailable")
    if value.get("stale"):
        raise RadarUpstreamError("NOAA nowCOAST radar metadata is stale")
    bounds = value.get("bounds")
    if not isinstance(bounds, dict) or any(key not in bounds for key in ("west", "east", "south", "north")):
        raise RadarUpstreamError("NOAA nowCOAST radar manifest has no coverage bounds")
    for field, low, high in (("west", -180, 180), ("east", -180, 180), ("south", -90, 90), ("north", -90, 90)):
        number = bounds.get(field)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not low <= number <= high:
            raise RadarUpstreamError("NOAA nowCOAST radar manifest has invalid coverage bounds")
    if bounds["west"] >= bounds["east"] or bounds["south"] >= bounds["north"]:
        raise RadarUpstreamError("NOAA nowCOAST radar coverage bounds are invalid")
    canonical_times = []
    for raw in value["times"]:
        if not isinstance(raw, str):
            raise RadarUpstreamError("NOAA nowCOAST radar manifest contains an invalid timestamp")
        try:
            timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError
            canonical_times.append(timestamp.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        except (ValueError, TypeError):
            raise RadarUpstreamError("NOAA nowCOAST radar manifest contains an invalid timestamp") from None
    latest = value.get("latest")
    try:
        latest_time = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        if latest_time.tzinfo is None:
            raise ValueError
        canonical_latest = latest_time.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError, AttributeError):
        canonical_latest = None
    if canonical_latest not in canonical_times:
        raise RadarUpstreamError("NOAA nowCOAST radar manifest latest time is not advertised")
    return value


def fetch_weather_manifest(product: str, timeout: float = 20) -> dict[str, Any]:
    if product not in PRODUCT_LAYERS:
        raise RadarRequestError("product must be radar, clouds, clouds-regional, or lightning")
    url = f"{_base_url()}/api/weather/manifest?product={product}"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        if len(response.content) > MAX_MANIFEST_BYTES:
            raise RadarUpstreamError("God’s Eye View returned oversized radar metadata")
        payload = response.json()
    except RadarUpstreamError:
        raise
    except (requests.RequestException, ValueError):
        raise RadarUpstreamError("God’s Eye View satellite/radar manifest request failed") from None
    return _validate_manifest(payload, product)


def fetch_radar_manifest(timeout: float = 20) -> dict[str, Any]:
    """Backward-compatible radar manifest fetcher."""
    return fetch_weather_manifest(PRODUCT, timeout)


def _validate_png(body: bytes, expected_width: int | None = None, expected_height: int | None = None) -> tuple[int, int]:
    if len(body) < 33 or len(body) > MAX_IMAGE_BYTES or body[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack_from(">I", body, 8)[0] != 13 or body[12:16] != b"IHDR":
        raise RadarUpstreamError("NOAA nowCOAST returned an invalid radar image")
    width, height = struct.unpack_from(">II", body, 16)
    if not width or not height or width > 4096 or height > 2048 or (expected_width and width != expected_width) or (expected_height and height != expected_height):
        raise RadarUpstreamError("NOAA nowCOAST returned an unsupported radar image size")
    return width, height


def _image_request(product: str, params: dict[str, Any], route: str, expected_width: int, expected_height: int, timeout: float = 30) -> tuple[bytes, dict[str, Any]]:
    query = {"product": product, **params}
    url = f"{_base_url()}/api/weather/{route}?{urlencode(query)}"
    try:
        response = requests.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        if not (response.headers.get("content-type") or "").lower().startswith("image/png"):
            raise RadarUpstreamError("God’s Eye View radar endpoint did not return PNG imagery")
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_IMAGE_BYTES:
                raise RadarUpstreamError("God’s Eye View returned oversized radar imagery")
        payload = bytes(body)
    except RadarUpstreamError:
        raise
    except requests.RequestException:
        raise RadarUpstreamError("God’s Eye View radar image request failed") from None
    width, height = _validate_png(payload, expected_width, expected_height)
    return payload, {"width": width, "height": height, "content_type": "image/png", "bytes": len(payload)}


def fetch_weather_image(product: str, time: str, size: str | None = None, bbox: str | None = None) -> tuple[bytes, dict[str, Any]]:
    if product not in PRODUCT_LAYERS:
        raise RadarRequestError("product must be radar, clouds, clouds-regional, or lightning")
    if not isinstance(time, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z", time):
        raise RadarRequestError("time must be an explicit UTC timestamp from the radar manifest")
    size = size or ("4096x2048" if bbox else ("2048x1024" if product == "clouds" else "4096x2048"))
    allowed_sizes = IMAGE_SIZES if bbox is not None else PRODUCT_IMAGE_SIZES[product]
    if size not in allowed_sizes:
        raise RadarRequestError("image size is unsupported for this satellite/radar product")
    params: dict[str, Any] = {"time": time, "size": size}
    if bbox is not None:
        if not isinstance(bbox, str) or len(bbox) > 96:
            raise RadarRequestError("bbox must be a bounded west,south,east,north window")
        parts = bbox.split(",")
        if len(parts) != 4 or any(not re.fullmatch(r"-?\d{1,3}(?:\.\d{1,6})?", part) for part in parts):
            raise RadarRequestError("bbox must contain four finite geographic bounds")
        west, south, east, north = (float(part) for part in parts)
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90) or abs((east - west) / (north - south) / 2 - 1) > 0.01:
            raise RadarRequestError("bbox must be a valid 2:1 geographic image window")
        params["bbox"] = bbox
    width, height = (int(v) for v in size.split("x"))
    return _image_request(product, params, "image", width, height)


def fetch_radar_image(time: str, size: str | None = None, bbox: str | None = None) -> tuple[bytes, dict[str, Any]]:
    return fetch_weather_image(PRODUCT, time, size=size, bbox=bbox)


def fetch_weather_tile(product: str, time: str, z: int, x: int, y: int, size: str = "256") -> tuple[bytes, dict[str, Any]]:
    if product not in PRODUCT_LAYERS:
        raise RadarRequestError("product must be radar, clouds, clouds-regional, or lightning")
    if not isinstance(time, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z", time):
        raise RadarRequestError("time must be an explicit UTC timestamp from the radar manifest")
    if size not in TILE_SIZES:
        raise RadarRequestError("tile size must be 256, 512, or 1024")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (z, x, y)) or z < 0 or z > 6 or x < 0 or x >= 2 ** (z + 1) or y < 0 or y >= 2 ** z:
        raise RadarRequestError("tile coordinate is outside the supported geographic scheme")
    dimension = int(size)
    return _image_request(product, {"time": time, "z": z, "x": x, "y": y, "size": size}, "tile", dimension, dimension)


def fetch_radar_tile(time: str, z: int, x: int, y: int, size: str = "256") -> tuple[bytes, dict[str, Any]]:
    return fetch_weather_tile(PRODUCT, time, z, x, y, size=size)
