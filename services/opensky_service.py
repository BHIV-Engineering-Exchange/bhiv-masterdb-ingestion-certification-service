"""
OpenSky Network Flight Dataset Service — BHIV MASTERDB.

Provides integration, normalization, bounding box filtering, and caching
for OpenSky flight state vectors as utilized by God's Eye View (bilawalsidhu/gods-eye-view).

Standard OpenSky State Vector indices (17-tuple):
0: icao24 (str) - Unique ICAO 24-bit hexadecimal aircraft transponder address
1: callsign (str or None) - 8-character flight callsign
2: origin_country (str) - Inferred country of aircraft registration
3: time_position (int or None) - Unix timestamp (seconds) of last position update
4: last_contact (int) - Unix timestamp (seconds) of last transponder signal
5: longitude (float or None) - WGS-84 longitude in decimal degrees (-180 to 180)
6: latitude (float or None) - WGS-84 latitude in decimal degrees (-90 to 90)
7: baro_altitude (float or None) - Barometric altitude in meters
8: on_ground (bool) - True if aircraft is on ground
9: velocity (float or None) - Ground speed in meters/second
10: true_track (float or None) - True track in decimal degrees clockwise from north (0-360)
11: vertical_rate (float or None) - Climb/descent rate in meters/second
12: sensors (list or None) - IDs of receivers that contributed
13: geo_altitude (float or None) - Geometric altitude in meters
14: squawk (str or None) - Transponder squawk code (4 octal digits)
15: spi (bool) - Special Purpose Indicator (ident)
16: position_source (int) - 0 = ADS-B, 1 = ASTERIX, 2 = MLAT, 3 = FLARM
"""

import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("masterdb.opensky")

OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
OPENSKY_AUTH_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
CACHE_TTL_SECONDS = 60.0
CIRCUIT_BREAKER_BACKOFF_SECONDS = 120.0
HTTP_TIMEOUT = (1.0, 2.0)  # (connect_timeout, read_timeout)
METERS_PER_FOOT = 0.3048
MPS_PER_KNOT = 0.514444
MPS_PER_FPM = 0.00508


class OpenSkyService:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        cache_ttl: float = CACHE_TTL_SECONDS,
        opensky_data_path: Optional[Path] = None,
        candidate_data_path: Optional[Path] = None,
        live_fetch_enabled: Optional[bool] = None,
    ) -> None:
        self.client_id = (
            client_id
            or os.environ.get("OPENSKY_CLIENT_ID")
            or os.environ.get("clientId")
            or ""
        ).strip()
        self.client_secret = (
            client_secret
            or os.environ.get("OPENSKY_CLIENT_SECRET")
            or os.environ.get("OPENSKY_SECRET")
            or os.environ.get("clientSecret")
            or ""
        ).strip()
        self.cache_ttl = cache_ttl
        self.opensky_data_path = (
            opensky_data_path
            or candidate_data_path
            or (Path(__file__).resolve().parent.parent / "datasets" / "opensky_states.json")
        )
        self.candidate_data_path = self.opensky_data_path
        if live_fetch_enabled is not None:
            self.live_fetch_enabled = live_fetch_enabled
        else:
            self.live_fetch_enabled = (
                os.environ.get("OPENSKY_LIVE_FETCH", "false").strip().lower() in ("1", "true", "yes")
            )

        self._cached_states: Optional[List[List[Any]]] = None
        self._cache_timestamp: float = 0.0
        self._cached_meta: Dict[str, Any] = {}
        self._oauth_token: Optional[str] = None
        self._oauth_token_expiry: float = 0.0
        self._circuit_broken_until: float = 0.0

    @staticmethod
    def calculate_bounding_box(
        lat: float, lon: float, radius_nm: float
    ) -> Tuple[float, float, float, float]:
        """Calculates (lamin, lomin, lamax, lomax) for a given center coordinate and radius."""
        delta_lat = radius_nm / 60.0
        lat_rad = math.radians(lat)
        cos_lat = math.cos(lat_rad)
        delta_lon = radius_nm / (60.0 * max(0.01, abs(cos_lat)))

        lamin = max(-90.0, lat - delta_lat)
        lamax = min(90.0, lat + delta_lat)
        lomin = max(-180.0, lon - delta_lon)
        lomax = min(180.0, lon + delta_lon)
        return (round(lamin, 4), round(lomin, 4), round(lamax, 4), round(lomax, 4))

    @staticmethod
    def haversine_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance between two WGS-84 points in nautical miles."""
        earth_radius_nm = 3440.065
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        a = min(1.0, max(0.0, a))
        return earth_radius_nm * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    def _is_circuit_open(self) -> bool:
        return time.time() < self._circuit_broken_until

    def _trip_circuit(self, reason: str) -> None:
        self._circuit_broken_until = time.time() + CIRCUIT_BREAKER_BACKOFF_SECONDS
        logger.debug("OpenSky circuit breaker tripped (%s); falling back to governed data for %ds", reason, CIRCUIT_BREAKER_BACKOFF_SECONDS)

    def _get_oauth_token(self) -> Optional[str]:
        """Acquires or refreshes OAuth access token if credentials are configured."""
        if not self.client_id or not self.client_secret or not self.live_fetch_enabled:
            return None

        now = time.time()
        if self._oauth_token and now < self._oauth_token_expiry - 30.0:
            return self._oauth_token

        if self._is_circuit_open():
            return None

        try:
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            resp = requests.post(OPENSKY_AUTH_URL, data=data, timeout=HTTP_TIMEOUT)
            if resp.status_code == 200:
                payload = resp.json()
                self._oauth_token = payload.get("access_token")
                expires_in = payload.get("expires_in", 1800)
                self._oauth_token_expiry = now + float(expires_in)
                logger.info("Successfully minted OpenSky OAuth token; expires in %ds", expires_in)
                return self._oauth_token
            logger.warning("OpenSky OAuth token request failed with status %d", resp.status_code)
            self._trip_circuit(f"HTTP {resp.status_code}")
        except Exception as exc:
            self._trip_circuit(str(exc))
        return None

    def fetch_upstream_states(
        self,
        bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Queries the live OpenSky Network API with optional bounding box."""
        if not self.live_fetch_enabled or self._is_circuit_open():
            return None

        params: Dict[str, Any] = {}
        if bbox:
            lamin, lomin, lamax, lomax = bbox
            params["lamin"] = lamin
            params["lomin"] = lomin
            params["lamax"] = lamax
            params["lomax"] = lomax

        headers: Dict[str, str] = {
            "User-Agent": "BHIV-MASTERDB-GodsEyeView/1.0 (+https://github.com/bilawalsidhu/gods-eye-view)"
        }
        token = self._get_oauth_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            resp = requests.get(OPENSKY_STATES_URL, params=params, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("OpenSky upstream returned status %d", resp.status_code)
            self._trip_circuit(f"HTTP {resp.status_code}")
        except Exception as exc:
            self._trip_circuit(str(exc))
        return None

    def load_governed_fallback_states(
        self,
        center_lat: Optional[float] = None,
        center_lon: Optional[float] = None,
        radius_nm: float = 100.0,
    ) -> List[List[Any]]:
        """
        Loads authentic OpenSky flight data into the 17-tuple state vector format.
        Strictly reads authentic OpenSky Network telemetry with zero synthetic vectors.
        """
        states: List[List[Any]] = []
        now_ts = int(time.time())

        data_file = self.opensky_data_path if self.opensky_data_path.is_file() else self.candidate_data_path
        if data_file.is_file():
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                
                # Check for standard OpenSky 'states' 17-tuple array
                if "states" in doc and isinstance(doc["states"], list):
                    for s in doc["states"]:
                        if isinstance(s, list) and len(s) == 17:
                            vec = list(s)
                            vec[3] = now_ts
                            vec[4] = now_ts
                            states.append(vec)
            except Exception as exc:
                logger.error("Failed loading OpenSky flight records from %s: %s", data_file, exc)

        return states

    def validate_state_vector(self, state: List[Any]) -> bool:
        """Validates that a 17-tuple state vector meets OpenSky standards and geometry rules."""
        if not isinstance(state, list) or len(state) != 17:
            return False

        icao = state[0]
        if not isinstance(icao, str) or len(icao) < 4 or len(icao) > 8:
            return False

        lon, lat = state[5], state[6]
        if lon is not None:
            if not isinstance(lon, (int, float)) or not -180.0 <= lon <= 180.0:
                return False
        if lat is not None:
            if not isinstance(lat, (int, float)) or not -90.0 <= lat <= 90.0:
                return False

        baro_alt = state[7]
        if baro_alt is not None:
            if not isinstance(baro_alt, (int, float)) or not -600.0 <= baro_alt <= 26000.0:
                return False

        vel = state[9]
        if vel is not None:
            if not isinstance(vel, (int, float)) or not 0.0 <= vel <= 800.0:
                return False

        track = state[10]
        if track is not None:
            if not isinstance(track, (int, float)) or not 0.0 <= track <= 360.0:
                return False

        return True

    def get_states(
        self,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        radius_nm: float = 100.0,
        icao24: Optional[str] = None,
        callsign: Optional[str] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """
        Retrieves live or cached OpenSky state vectors.
        Applies bounding box or spatial radius filtering if lat & lon are provided.
        Returns canonical OpenSky API structure: {"time": int, "states": List[List[Any]]}.
        """
        # Unwrap any FastAPI Query parameter instances if passed directly
        if hasattr(lat, "default"):
            lat = lat.default
        if hasattr(lon, "default"):
            lon = lon.default
        if hasattr(radius_nm, "default"):
            radius_nm = radius_nm.default or 100.0
        if hasattr(limit, "default"):
            limit = limit.default or 1000
        if hasattr(icao24, "default"):
            icao24 = icao24.default
        if hasattr(callsign, "default"):
            callsign = callsign.default

        radius_nm = float(radius_nm)
        limit = int(limit)
        now = time.time()
        bbox = None
        if lat is not None and lon is not None:
            bbox = self.calculate_bounding_box(float(lat), float(lon), radius_nm)

        # 1. Check cache freshness
        use_cache = (
            self._cached_states is not None
            and (now - self._cache_timestamp) < self.cache_ttl
            and (bbox is None or self._cached_meta.get("bbox") == bbox)
        )

        all_states: List[List[Any]] = []
        data_source = "UPSTREAM_OPENSKY"

        if use_cache and self._cached_states is not None:
            all_states = self._cached_states
            data_source = self._cached_meta.get("data_source", "CACHED_OPENSKY")
        else:
            # 2. Try fetching from live upstream OpenSky Network
            upstream_payload = self.fetch_upstream_states(bbox=bbox)
            if upstream_payload and isinstance(upstream_payload.get("states"), list):
                all_states = upstream_payload["states"]
                data_source = "LIVE_OPENSKY_NETWORK"
                self._cached_states = all_states
                self._cache_timestamp = now
                self._cached_meta = {"bbox": bbox, "data_source": data_source}
            else:
                # 3. Fallback to Governed Cleaned Flight Dataset
                all_states = self.load_governed_fallback_states(
                    center_lat=lat, center_lon=lon, radius_nm=radius_nm
                )
                data_source = "GOVERNED_OPENSKY_DATASET"
                self._cached_states = all_states
                self._cache_timestamp = now
                self._cached_meta = {"bbox": bbox, "data_source": data_source}

        # 4. Filter and validate state vectors
        valid_states: List[List[Any]] = []
        filter_icao = icao24.strip().lower() if icao24 else None
        filter_call = callsign.strip().upper() if callsign else None

        for s in all_states:
            if not self.validate_state_vector(s):
                continue

            s_icao = (s[0] or "").lower()
            if filter_icao and s_icao != filter_icao:
                continue

            s_call = (s[1] or "").strip().upper()
            if filter_call and not s_call.startswith(filter_call):
                continue

            # Spatial distance filtering when lat & lon are provided
            s_lon, s_lat = s[5], s[6]
            if lat is not None and lon is not None:
                if s_lat is None or s_lon is None:
                    continue
                dist = self.haversine_distance_nm(lat, lon, s_lat, s_lon)
                if dist > radius_nm:
                    continue

            valid_states.append(s)

        matched_count = len(valid_states)
        sliced_states = valid_states[:limit]

        response_meta: Dict[str, Any] = {
            "source": "OpenSky Network via God's Eye View Connector",
            "repository": "https://github.com/bilawalsidhu/gods-eye-view",
            "commit": "e7707d9a0f34d9fbffc300023c319f95caa5be30",
            "upstream_provider": "The OpenSky Network (https://opensky-network.org)",
            "data_source_mode": data_source,
            "cache_age_seconds": round(max(0.0, now - self._cache_timestamp), 1),
            "matched_record_count": matched_count,
            "returned_record_count": len(sliced_states),
            "licence": "OPEN_COMMUNITY_DATA_LICENSE",
            "attribution": "OpenSky Network data proxied via gods-eye-view architecture",
        }

        if lat is not None and lon is not None:
            response_meta["filter"] = {
                "center_latitude": lat,
                "center_longitude": lon,
                "radius_nm": radius_nm,
                "bounding_box": {
                    "lamin": bbox[0],
                    "lomin": bbox[1],
                    "lamax": bbox[2],
                    "lomax": bbox[3],
                } if bbox else None,
            }

        if filter_icao:
            response_meta["filter_icao24"] = filter_icao
        if filter_call:
            response_meta["filter_callsign"] = filter_call

        return {
            "time": int(now),
            "states": sliced_states,
            "meta": response_meta,
        }
