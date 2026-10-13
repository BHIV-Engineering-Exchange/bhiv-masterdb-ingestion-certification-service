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
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse


def is_ephemeral_db_url(url: Optional[str]) -> bool:
    """Returns True if the database URL specifies an ephemeral / in-memory store."""
    if not url or not str(url).strip():
        return False
    u = str(url).strip()
    if u.lower() == ":memory:":
        return True
    try:
        parsed = urlparse(u)
        scheme = (parsed.scheme or "").lower()
        if scheme in ("memory", "mock"):
            return True
        if scheme.startswith("sqlite"):
            query = (parsed.query or "").lower()
            if "mode=memory" in query:
                return True
            clean_path = (parsed.path or "").strip("/")
            if not clean_path and not parsed.netloc:
                return True
            if clean_path.lower() == ":memory:" or parsed.netloc.lower() == ":memory:":
                return True
            return False
    except Exception:
        return False
    return False


def sanitize_db_url(url: Optional[str]) -> str:
    """Masks database passwords in connection URLs to prevent secret leakage in logs/errors."""
    if not url or not str(url).strip():
        return ""
    u = str(url).strip()
    try:
        parsed = urlparse(u)
        if parsed.password:
            netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
            return parsed._replace(netloc=netloc).geturl()
        return u
    except Exception:
        return "<sanitized-database-url>"


def validate_production_persistence(
    storage_dir: Optional[str],
    database_url: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """
    Validates whether persistent storage is properly configured for production.
    Returns (is_valid, error_message).
    """
    db_url_str = (database_url or "").strip()
    storage_dir_str = (storage_dir or "").strip()

    if db_url_str:
        if is_ephemeral_db_url(db_url_str):
            sanitized = sanitize_db_url(db_url_str)
            return (
                False,
                f"Configured MASTERDB_DATABASE_URL ('{sanitized}') is ephemeral and cannot be used in production mode. "
                "A persistent database URL or persistent MASTERDB_STORAGE_DIR is required.",
            )
        status = _url_status(db_url_str)
        if status == "set_but_malformed":
            return (
                False,
                "Configured MASTERDB_DATABASE_URL is malformed. A valid persistent database URL is required.",
            )
        return (True, None)

    if storage_dir_str:
        if storage_dir_str == ":memory:":
            return (
                False,
                "Configured MASTERDB_STORAGE_DIR is ephemeral (':memory:'). "
                "A persistent storage directory path is required in production mode.",
            )
        return (True, None)

    return (
        False,
        "Production mode requires persistent storage configuration (MASTERDB_DATABASE_URL or MASTERDB_STORAGE_DIR). "
        "Ephemeral in-memory storage is not permitted.",
    )


def _url_status(value: str) -> str:
    if not value:
        return "not_set"
    try:
        parsed = urlparse(value)
        if not parsed.scheme:
            return "set_but_malformed"
        if parsed.scheme.startswith("sqlite"):
            if not parsed.netloc and not parsed.path:
                return "set_but_malformed"
            return "set_and_well_formed"
        if not parsed.netloc:
            return "set_but_malformed"
        return "set_and_well_formed"
    except Exception:
        return "set_but_malformed"


def validate_configuration() -> Dict[str, Any]:
    report: Dict[str, Any] = {}

    auth_secret = os.environ.get("AUTH_JWT_SECRET") or os.environ.get("JWT_SECRET")
    env_mode = (
        os.environ.get("ENVIRONMENT")
        or os.environ.get("APP_ENV")
        or os.environ.get("MASTERDB_ENV")
        or ""
    ).strip().lower()
    is_production = env_mode in ("production", "prod")

    if auth_secret:
        auth_secret_note = None
    elif is_production:
        auth_secret_note = (
            "CRITICAL: AUTH_JWT_SECRET is unset in production mode — process cannot start safely with a random secret"
        )
    else:
        auth_secret_note = (
            "unset -> a random per-process secret is generated at startup; tokens "
            "won't validate across restarts or multiple workers"
        )

    report["AUTH_JWT_SECRET"] = {
        "set": bool(auth_secret),
        "note": auth_secret_note,
    }

    auth_pw = (
        os.environ.get("AUTH_PASSWORD")
        or os.environ.get("MASTERDB_AUTH_PASSWORD")
        or os.environ.get("ADMIN_PASSWORD")
    )
    report["AUTH_PASSWORD"] = {
        "set": bool(auth_pw),
        "note": "unset -> authentication fails closed; no tokens can be issued" if not auth_pw else None,
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
        if is_production:
            report["persistence"] = {
                "mode": "in_memory",
                "note": "CRITICAL: Ephemeral in-memory storage is not permitted in production mode — process requires MASTERDB_DATABASE_URL or MASTERDB_STORAGE_DIR",
            }
        else:
            report["persistence"] = {
                "mode": "in_memory",
                "note": "no persistence configured — all data is lost on restart",
            }
    elif db_url and is_ephemeral_db_url(db_url):
        report["MASTERDB_DATABASE_URL"]["ephemeral"] = True
        if is_production:
            report["persistence"] = {
                "mode": "ephemeral",
                "note": "CRITICAL: Ephemeral database URL is not permitted in production mode",
            }
        else:
            report["persistence"] = {
                "mode": "ephemeral",
                "note": "ephemeral database configured — data lost on restart",
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
