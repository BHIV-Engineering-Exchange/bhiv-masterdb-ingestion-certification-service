"""Fetch and normalize a bounded batch of live AISStream position messages."""
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

import websocket


AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"


class AISStreamConfigurationError(RuntimeError):
    pass


class AISStreamConnectionError(RuntimeError):
    pass


def normalize_position(message: Dict[str, Any]) -> Dict[str, Any] | None:
    """Return a store-ready position or None for a non-position/invalid message."""
    if message.get("MessageType") != "PositionReport":
        return None
    metadata = message.get("MetaData") or {}
    position = (message.get("Message") or {}).get("PositionReport") or {}
    vessel_id = metadata.get("MMSI") or position.get("UserID")
    latitude = metadata.get("Latitude", position.get("Latitude"))
    longitude = metadata.get("Longitude", position.get("Longitude"))
    if not vessel_id or isinstance(latitude, bool) or isinstance(longitude, bool):
        return None
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return {
        "vessel_id": str(vessel_id),
        "source": "AISStream",
        "latitude": latitude,
        "longitude": longitude,
        "speed_knots": position.get("Sog"),
        "course_degrees": position.get("Cog"),
        "ais_timestamp_utc_second": position.get("Timestamp"),
        "received_at_utc": datetime.now(timezone.utc).isoformat(),
        "message_type": message["MessageType"],
        "metadata": metadata,
    }


class AISStreamConnector:
    """One-shot server-side subscriber with bounded reconnect attempts."""

    def __init__(
        self,
        api_key: str | None = None,
        connection_factory: Callable[..., Any] = websocket.create_connection,
    ) -> None:
        self.api_key = api_key or os.environ.get("AISSTREAM_API_KEY")
        self.connection_factory = connection_factory

    def fetch_positions(
        self,
        bounding_boxes: List[List[List[float]]],
        max_messages: int = 25,
        timeout_seconds: float = 15,
        reconnect_attempts: int = 2,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise AISStreamConfigurationError("AISSTREAM_API_KEY is not configured")
        if not bounding_boxes:
            raise AISStreamConfigurationError("At least one AISStream bounding box is required")
        subscription = {
            "APIKey": self.api_key,
            "BoundingBoxes": bounding_boxes,
            "FilterMessageTypes": ["PositionReport"],
        }
        observations: List[Dict[str, Any]] = []
        errors: List[str] = []
        for attempt in range(reconnect_attempts + 1):
            connection = None
            try:
                connection = self.connection_factory(AISSTREAM_URL, timeout=timeout_seconds)
                connection.send(json.dumps(subscription))
                deadline = time.monotonic() + timeout_seconds
                while len(observations) < max_messages and time.monotonic() < deadline:
                    payload = connection.recv()
                    if isinstance(payload, bytes):
                        payload = payload.decode("utf-8")
                    try:
                        normalized = normalize_position(json.loads(payload))
                    except (TypeError, ValueError, UnicodeDecodeError):
                        continue
                    if normalized:
                        observations.append(normalized)
                if observations:
                    break
            except Exception as exc:
                errors.append(type(exc).__name__)
                if attempt == reconnect_attempts:
                    raise AISStreamConnectionError("AISStream connection failed after reconnect attempts") from exc
            finally:
                if connection is not None:
                    connection.close()
        return {
            "source": "AISStream",
            "dataset": "aisstream_vessel_positions",
            "record_count": len(observations),
            "observations": observations,
            "connection_errors": errors,
        }


def fetch_aisstream_positions(**kwargs: Any) -> Dict[str, Any]:
    return AISStreamConnector().fetch_positions(**kwargs)
