"""
Configuration validation and reporting.

Checks every environment variable this service actually reads (see
.env.example for the full list) and reports, per variable: whether it's
set, and — where checkable without a live network call — whether the
value is at least well-formed. This does NOT verify a value is *correct*
(e.g. it can't confirm AUTH_JWT_SECRET is the right secret, only that
something is set) and does NOT make any live network calls to verify
MDU_BASE_URL/PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE/etc. actually reach anything
— that's what /ready and the individual clients' health checks are for.

Never returns actual secret VALUES (AUTH_JWT_SECRET, MDU_API_KEY) in its
report — only whether they're set — since this is designed to be safe to
expose over an authenticated admin endpoint without leaking credentials
into logs or API responses.
"""
import os
from typing import Any, Dict
from urllib.parse import urlparse


def _url_status(value: str) -> str:
    if not value:
        return "not_set"
    try:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return "set_but_malformed"
        return "set_and_well_formed"
    except Exception:
        return "set_but_malformed"


def validate_configuration() -> Dict[str, Any]:
    report: Dict[str, Any] = {}

    auth_secret = os.environ.get("AUTH_JWT_SECRET")
    report["AUTH_JWT_SECRET"] = {
        "set": bool(auth_secret),
        "note": "unset -> a random per-process secret is generated at startup; tokens "
        "won't validate across restarts or multiple workers" if not auth_secret else None,
    }

    storage_dir = os.environ.get("MASTERDB_STORAGE_DIR")
    db_url = os.environ.get("MASTERDB_DATABASE_URL")
    report["MASTERDB_STORAGE_DIR"] = {"set": bool(storage_dir)}
    report["MASTERDB_DATABASE_URL"] = {"set": bool(db_url), "format": _url_status(db_url) if db_url else "not_set"}
    if storage_dir and db_url:
        report["MASTERDB_DATABASE_URL"]["note"] = (
            "both MASTERDB_STORAGE_DIR and MASTERDB_DATABASE_URL are set — "
            "MASTERDB_DATABASE_URL takes priority, MASTERDB_STORAGE_DIR is ignored"
        )
    if not storage_dir and not db_url:
        report["persistence"] = {
            "mode": "in_memory",
            "note": "no persistence configured — all data is lost on restart",
        }

    mdu_url = os.environ.get("MDU_BASE_URL")
    mdu_key = os.environ.get("MDU_API_KEY")
    report["MDU_BASE_URL"] = {"set": bool(mdu_url), "format": _url_status(mdu_url) if mdu_url else "not_set"}
    report["MDU_API_KEY"] = {"set": bool(mdu_key)}
    if bool(mdu_url) != bool(mdu_key):
        report["MDU_BASE_URL"]["note"] = "only one of MDU_BASE_URL/MDU_API_KEY is set — MDU calls will fail"

    insightbridge_url = os.environ.get("PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE")
    report["PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE"] = {
        "set": bool(insightbridge_url),
        "format": _url_status(insightbridge_url) if insightbridge_url else "not_set",
    }

    rate_max = os.environ.get("RATE_LIMIT_MAX_REQUESTS", "120")
    rate_window = os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")
    rate_valid = True
    try:
        int(rate_max)
        float(rate_window)
    except ValueError:
        rate_valid = False
    report["RATE_LIMIT_MAX_REQUESTS"] = {"value": rate_max, "valid": rate_valid}
    report["RATE_LIMIT_WINDOW_SECONDS"] = {"value": rate_window, "valid": rate_valid}

    return report


def summarize_for_startup_log(report: Dict[str, Any]) -> str:
    """One-line-per-item summary suitable for a startup log message."""
    lines = ["Configuration at startup:"]
    for key, status in report.items():
        if key == "persistence":
            lines.append(f"  persistence: {status['mode']} — {status['note']}")
            continue
        set_str = "SET" if status.get("set") else "unset"
        note = f" ({status['note']})" if status.get("note") else ""
        lines.append(f"  {key}: {set_str}{note}")
    return "\n".join(lines)
