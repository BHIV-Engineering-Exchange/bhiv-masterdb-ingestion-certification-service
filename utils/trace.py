"""
Trace ID utilities for MASTERDB and ecosystem correlation.

Generates and validates 32-character hexadecimal trace IDs conforming to
W3C traceparent / distributed tracing conventions, ensuring continuity across
the Upload -> Certification -> Ingestion -> MDU Provenance lifecycle.
"""
import re
import uuid
from typing import Optional

_TRACE_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def generate_trace_id() -> str:
    """Generate a standard 32-character lowercase hexadecimal trace ID."""
    return uuid.uuid4().hex


def is_valid_trace_id(candidate: Optional[str]) -> bool:
    """Check if candidate is a valid 32-character hexadecimal trace ID."""
    if not candidate or not isinstance(candidate, str):
        return False
    return bool(_TRACE_ID_RE.match(candidate))


def normalize_trace_id(candidate: Optional[str]) -> str:
    """
    Normalize a candidate trace ID to standard 32-character hex format.

    Handles:
      - Valid 32-hex: lowercased and returned.
      - UUID with hyphens (36 chars): hyphens removed, returning 32-hex.
      - Legacy prefixed trace ID (e.g. 'trace-{hex}'): prefix stripped if 32-hex.
      - Missing or invalid format: generates and returns a new 32-hex trace ID.
    """
    if not candidate or not isinstance(candidate, str):
        return generate_trace_id()

    cleaned = candidate.strip()
    if is_valid_trace_id(cleaned):
        return cleaned.lower()

    # Check for UUID with hyphens (8-4-4-4-12)
    unhyphenated = cleaned.replace("-", "")
    if is_valid_trace_id(unhyphenated):
        return unhyphenated.lower()

    # Check for legacy 'trace-' prefix
    if cleaned.lower().startswith("trace-"):
        stripped = cleaned[6:]
        if is_valid_trace_id(stripped):
            return stripped.lower()

    # Fallback to generating a fresh compliant trace ID
    return generate_trace_id()
