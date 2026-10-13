#!/usr/bin/env python3
"""
BHIV vNEXT MASTERDB-GEO-QUEST-01: Data Collection Script
Source: adsb.lol API (God's Eye View reference network)
Geographic endpoint: https://api.adsb.lol/v2/lat/19.0760/lon/72.8777/dist/100

CRITICAL DATA INTEGRITY RULE:
- Uses ONLY real data returned by the actual adsb.lol API.
- Never creates, generates, invents, simulates, mocks, fabricates, or hard-codes any aircraft records.
- If the API request fails or is unreachable, no fake data is created and status is reported as FAILED.
"""

import sys
import os
import json
import argparse
from datetime import datetime, timezone
import requests

DEFAULT_LAT = 19.0760
DEFAULT_LON = 72.8777
DEFAULT_DIST = 100
DEFAULT_BASE_URL = "https://api.adsb.lol/v2"
DEFAULT_TIMEOUT = 25  # seconds

def build_api_url(lat: float, lon: float, dist: float, base_url: str = DEFAULT_BASE_URL) -> str:
    """Build the exact geographic query endpoint."""
    return f"{base_url.rstrip('/')}/lat/{lat:.4f}/lon/{lon:.4f}/dist/{dist:.0f}"

def collect_live_aircraft_data(
    url: str,
    output_raw_file: str,
    output_meta_file: str,
    timeout: int = DEFAULT_TIMEOUT
) -> dict:
    """
    Make real HTTP GET request to the adsb.lol API.
    Saves the exact, unmodified API response to output_raw_file.
    Saves acquisition metadata to output_meta_file.
    """
    utc_start = datetime.now(timezone.utc)
    acquisition_timestamp = utc_start.isoformat()
    
    print("=" * 70)
    print("BHIV vNEXT MASTERDB-GEO-QUEST-01: REAL DATA ACQUISITION")
    print("=" * 70)
    print(f"Target URL:        {url}")
    print(f"Acquisition UTC:   {acquisition_timestamp}")
    print(f"Timeout:           {timeout}s")
    print(f"Raw Output Path:   {output_raw_file}")
    print(f"Meta Output Path:  {output_meta_file}")
    print("-" * 70)

    headers = {
        "User-Agent": "BHIV-vNEXT-MasterDB-Collector/1.0 (Data-Governance-Pipeline; Contact: BHIV-Engineering)",
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        elapsed_sec = response.elapsed.total_seconds()
        http_status = response.status_code
        
        print(f"HTTP Status Code:  {http_status}")
        print(f"Response Time:     {elapsed_sec:.3f}s")
        
        if http_status != 200:
            error_msg = f"API returned non-200 HTTP status: {http_status}. Response: {response.text[:300]}"
            print(f"\n[ERROR] {error_msg}")
            print("[CRITICAL INTEGRITY ENFORCEMENT] No aircraft records will be created or fabricated.")
            # Record failed acquisition attempt
            meta_failure = {
                "status": "FAIL",
                "source_url": url,
                "utc_timestamp": acquisition_timestamp,
                "http_status": http_status,
                "error": error_msg,
                "live_data_collected": False
            }
            os.makedirs(os.path.dirname(output_meta_file), exist_ok=True)
            with open(output_meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_failure, f, indent=2)
            sys.exit(1)

        try:
            raw_json_data = response.json()
        except json.JSONDecodeError as jde:
            error_msg = f"Failed to parse response as valid JSON: {jde}. Raw snippet: {response.text[:200]}"
            print(f"\n[ERROR] {error_msg}")
            print("[CRITICAL INTEGRITY ENFORCEMENT] Invalid JSON received. No aircraft records will be created.")
            meta_failure = {
                "status": "FAIL",
                "source_url": url,
                "utc_timestamp": acquisition_timestamp,
                "http_status": http_status,
                "error": error_msg,
                "live_data_collected": False
            }
            os.makedirs(os.path.dirname(output_meta_file), exist_ok=True)
            with open(output_meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_failure, f, indent=2)
            sys.exit(1)

        # Verify that response is a dictionary and contains aircraft data structure
        if not isinstance(raw_json_data, dict):
            error_msg = f"Unexpected payload type: expected JSON object, got {type(raw_json_data).__name__}"
            print(f"\n[ERROR] {error_msg}")
            sys.exit(1)

        aircraft_list = raw_json_data.get("ac", [])
        aircraft_count = len(aircraft_list) if isinstance(aircraft_list, list) else 0

        print(f"Aircraft Count:    {aircraft_count} real records returned")
        print(f"Payload Size:      {len(response.content)} bytes")

        # Save EXACT unmodified API response
        os.makedirs(os.path.dirname(output_raw_file), exist_ok=True)
        with open(output_raw_file, "w", encoding="utf-8") as f:
            # Serializing the exact json payload returned by the API
            json.dump(raw_json_data, f, indent=2, ensure_ascii=False)
        print(f"[SUCCESS] Saved exact API response to: {output_raw_file}")

        # Save acquisition metadata clearly separated
        acquisition_meta = {
            "status": "SUCCESS",
            "source_url": url,
            "utc_acquisition_timestamp": acquisition_timestamp,
            "http_status": http_status,
            "response_time_seconds": elapsed_sec,
            "content_length_bytes": len(response.content),
            "response_headers": dict(response.headers),
            "total_aircraft_records_raw": aircraft_count,
            "api_now_timestamp": raw_json_data.get("now"),
            "api_msg": raw_json_data.get("msg"),
            "api_total_field": raw_json_data.get("total"),
            "collector_script": os.path.basename(__file__),
            "live_data_collected": True
        }
        os.makedirs(os.path.dirname(output_meta_file), exist_ok=True)
        with open(output_meta_file, "w", encoding="utf-8") as f:
            json.dump(acquisition_meta, f, indent=2)
        print(f"[SUCCESS] Saved acquisition metadata to: {output_meta_file}")
        print("=" * 70)

        return acquisition_meta

    except requests.exceptions.Timeout as te:
        error_msg = f"HTTP request timed out after {timeout} seconds: {te}"
        print(f"\n[ERROR] {error_msg}")
        print("[CRITICAL INTEGRITY ENFORCEMENT] No fake data will be generated. Status: FAIL")
        sys.exit(1)
    except requests.exceptions.ConnectionError as ce:
        error_msg = f"Network connection error contacting adsb.lol: {ce}"
        print(f"\n[ERROR] {error_msg}")
        print("[CRITICAL INTEGRITY ENFORCEMENT] API unreachable. Status: FAIL")
        sys.exit(1)
    except requests.exceptions.RequestException as re:
        error_msg = f"Request exception during API query: {re}"
        print(f"\n[ERROR] {error_msg}")
        print("[CRITICAL INTEGRITY ENFORCEMENT] Status: FAIL")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Collect live ADS-B aircraft data from adsb.lol API")
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT, help=f"Query center latitude (default: {DEFAULT_LAT})")
    parser.add_argument("--lon", type=float, default=DEFAULT_LON, help=f"Query center longitude (default: {DEFAULT_LON})")
    parser.add_argument("--dist", type=float, default=DEFAULT_DIST, help=f"Query radius in nautical miles (default: {DEFAULT_DIST})")
    parser.add_argument("--output-raw", type=str, default=None, help="Output path for raw JSON")
    parser.add_argument("--output-meta", type=str, default=None, help="Output path for acquisition metadata JSON")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    
    args = parser.parse_args()

    # Determine base directory relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    
    raw_path = args.output_raw or os.path.join(project_root, "raw", "aircraft_raw.json")
    meta_path = args.output_meta or os.path.join(project_root, "raw", "acquisition_metadata.json")

    url = build_api_url(args.lat, args.lon, args.dist)
    collect_live_aircraft_data(url, raw_path, meta_path, timeout=args.timeout)

if __name__ == "__main__":
    main()
