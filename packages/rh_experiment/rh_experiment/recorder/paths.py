"""Deterministic filesystem-safe encoding for opaque protocol identifiers."""

from __future__ import annotations

import hashlib
from urllib.parse import quote

_MAX_COMPONENT_BYTES = 180


def safe_path_component(identifier: str) -> str:
    """Encode one opaque ID without rejecting valid protocol characters."""

    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("identifier must be a non-empty string")
    encoded = quote(identifier, safe="-_").replace(".", "%2E")
    if len(encoded.encode("utf-8")) <= _MAX_COMPONENT_BYTES:
        return encoded
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
    prefix = encoded.encode("utf-8")[:150].decode("utf-8", errors="ignore")
    return f"{prefix}--{digest}"
