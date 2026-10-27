"""Fetch and decode God's Eye View's TomTom relative-flow vector tiles."""
import math
import os
from datetime import datetime, timezone
from typing import Any

import requests


TOMTOM_TILE_URL = "https://api.tomtom.com/traffic/map/4/tile/flow/relative"
MIN_ZOOM, MAX_ZOOM, MAX_TILES = 8, 16, 16
MAX_TILE_BYTES = 8 * 1024 * 1024


class TomTomConfigurationError(RuntimeError):
    pass


class TomTomUpstreamError(RuntimeError):
    pass


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 70:
            break
    raise ValueError("Malformed protobuf varint")


def _fields(data: bytes):
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("Invalid protobuf field number")
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire == 1:
            value, offset = data[offset:offset + 8], offset + 8
        elif wire == 2:
            length, offset = _varint(data, offset)
            value, offset = data[offset:offset + length], offset + length
        elif wire == 5:
            value, offset = data[offset:offset + 4], offset + 4
        else:
            raise ValueError("Unsupported protobuf wire type")
        if offset > len(data):
            raise ValueError("Truncated protobuf field")
        yield number, wire, value


def _packed_varints(data: bytes) -> list[int]:
    values, offset = [], 0
    while offset < len(data):
        value, offset = _varint(data, offset)
        values.append(value)
    return values


def _decode_value(data: bytes) -> Any:
    for number, wire, value in _fields(data):
        if number == 1 and wire == 2:
            return value.decode("utf-8")
        if number == 2 and wire == 5:
            import struct
            return struct.unpack("<f", value)[0]
        if number == 3 and wire == 1:
            import struct
            return struct.unpack("<d", value)[0]
        if number in (4, 5) and wire == 0:
            return value
        if number == 6 and wire == 0:
            return (value >> 1) ^ -(value & 1)
        if number == 7 and wire == 0:
            return bool(value)
    return None


def _decode_geometry(commands: list[int], extent: int, z: int, x: int, y: int) -> list[list[list[float]]]:
    cursor = 0
    px = py = 0
    lines: list[list[list[float]]] = []
    current: list[list[float]] = []
    n = 2 ** z

    def coordinate(ix: int, iy: int) -> list[float]:
        lon = ((x + ix / extent) / n) * 360 - 180
        mercator_y = math.pi * (1 - 2 * (y + iy / extent) / n)
        lat = math.degrees(math.atan(math.sinh(mercator_y)))
        return [lon, lat]

    while cursor < len(commands):
        command_integer = commands[cursor]
        cursor += 1
        command, count = command_integer & 7, command_integer >> 3
        if count < 1:
            raise ValueError("Invalid vector-tile geometry command")
        if command in (1, 2):  # MoveTo / LineTo; coordinate deltas are zig-zag encoded.
            for index in range(count):
                if cursor + 1 >= len(commands):
                    raise ValueError("Truncated vector-tile geometry")
                dx, dy = commands[cursor], commands[cursor + 1]
                cursor += 2
                px += (dx >> 1) ^ -(dx & 1)
                py += (dy >> 1) ^ -(dy & 1)
                if command == 1:
                    if len(current) >= 2:
                        lines.append(current)
                    current = []
                current.append(coordinate(px, py))
        elif command == 7:  # ClosePath is not expected for a line layer.
            continue
        else:
            raise ValueError("Unsupported vector-tile geometry command")
    if len(current) >= 2:
        lines.append(current)
    return lines


def decode_flow_tile(data: bytes, z: int, x: int, y: int, fetched_at_utc: str) -> list[dict[str, Any]]:
    """Decode the `Traffic flow` MVT layer into store-ready road segments."""
    if not data or len(data) > MAX_TILE_BYTES:
        raise ValueError("Invalid or oversized vector tile")
    layer = None
    for number, wire, value in _fields(data):
        if number == 3 and wire == 2:
            layer_fields = list(_fields(value))
            name = next((v.decode("utf-8") for n, w, v in layer_fields if n == 1 and w == 2), None)
            if name == "Traffic flow":
                layer = layer_fields
                break
    if layer is None:
        return []
    keys = [value.decode("utf-8") for n, w, value in layer if n == 3 and w == 2]
    values = [_decode_value(value) for n, w, value in layer if n == 4 and w == 2]
    extent = next((value for n, w, value in layer if n == 5 and w == 0), 4096)
    segments = []
    for number, wire, feature_data in layer:
        if number != 2 or wire != 2:
            continue
        feature = list(_fields(feature_data))
        geom_type = next((value for n, w, value in feature if n == 3 and w == 0), 0)
        if geom_type != 2:
            continue
        tags = []
        for n, w, value in feature:
            if n == 2:
                tags.extend(_packed_varints(value) if w == 2 else [value])
        properties = {}
        for i in range(0, len(tags) - 1, 2):
            ki, vi = tags[i], tags[i + 1]
            if ki < len(keys) and vi < len(values):
                properties[keys[ki]] = values[vi]
        raw_level = properties.get("traffic_level")
        closure = properties.get("road_closure") is True
        if isinstance(raw_level, bool) or not isinstance(raw_level, (int, float)):
            if not closure:
                continue
            speed_ratio = 0.0
        else:
            speed_ratio = min(1.0, max(0.0, float(raw_level)))
        commands = []
        for n, w, value in feature:
            if n == 4:
                commands.extend(_packed_varints(value) if w == 2 else [value])
        for coords in _decode_geometry(commands, int(extent), z, x, y):
            segments.append({
                "source": "TomTom Traffic API", "tile": {"z": z, "x": x, "y": y},
                "traffic_style": "relative", "traffic_level": speed_ratio,
                "speed_ratio": speed_ratio, "congestion_ratio": 1.0 - speed_ratio,
                "current_speed_kph": properties.get("current_speed"),
                "free_flow_speed_kph": properties.get("free_flow_speed"),
                "road_type": properties.get("road_type"),
                "road_coverage": properties.get("traffic_road_coverage"),
                "left_hand_traffic": bool(properties.get("left_hand_traffic", False)),
                "road_closure": closure, "coordinates": coords,
                "observation_time_utc": fetched_at_utc,
            })
    return segments


def validate_tile_coord(tile: Any) -> dict[str, int]:
    if not isinstance(tile, dict):
        raise ValueError("Each tile must be an object with z, x, and y")
    coords = {}
    for name in ("z", "x", "y"):
        value = tile.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"tile {name} must be an integer")
        coords[name] = value
    z, x, y = coords["z"], coords["x"], coords["y"]
    if not MIN_ZOOM <= z <= MAX_ZOOM or not 0 <= x < 2 ** z or not 0 <= y < 2 ** z:
        raise ValueError("Tile coordinates are outside the supported TomTom zoom range (8-16)")
    return coords


def fetch_flow_tiles(tiles: list[dict[str, int]], timeout_seconds: float = 20) -> dict[str, Any]:
    key = os.environ.get("TOMTOM_API_KEY")
    if not key:
        raise TomTomConfigurationError("TOMTOM_API_KEY is not configured")
    if not isinstance(tiles, list) or not tiles or len(tiles) > MAX_TILES:
        raise ValueError(f"tiles must contain 1 to {MAX_TILES} tile coordinates")
    observations = []
    tile_results = []
    for raw_tile in tiles:
        tile = validate_tile_coord(raw_tile)
        try:
            response = requests.get(
                f"{TOMTOM_TILE_URL}/{tile['z']}/{tile['x']}/{tile['y']}.pbf",
                params={"key": key}, timeout=timeout_seconds,
            )
            response.raise_for_status()
            if len(response.content) > MAX_TILE_BYTES:
                raise TomTomUpstreamError("TomTom returned an oversized traffic tile")
            date_header = response.headers.get("Date")
            observed = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc).isoformat() if date_header else datetime.now(timezone.utc).isoformat()
            segments = decode_flow_tile(response.content, tile["z"], tile["x"], tile["y"], observed)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise TomTomUpstreamError(f"TomTom traffic-flow request returned HTTP {status}") from None
        except requests.RequestException:
            raise TomTomUpstreamError("TomTom traffic-flow network request failed") from None
        except (ValueError, OverflowError) as exc:
            if isinstance(exc, TomTomUpstreamError):
                raise
            raise TomTomUpstreamError("TomTom returned an invalid traffic-flow tile") from None
        observations.extend(segments)
        tile_results.append({**tile, "segment_count": len(segments), "observation_time_utc": observed})
    return {"source": "TomTom Traffic API", "dataset": "tomtom_traffic_flow_segments", "tile_count": len(tiles), "record_count": len(observations), "tiles": tile_results, "observations": observations}
