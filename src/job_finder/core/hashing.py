"""Deterministic hashing for versioned configuration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def configuration_hash(content: Mapping[str, object]) -> str:
    """Return a stable SHA-256 hash for JSON-compatible configuration content."""
    try:
        canonical = json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        msg = "configuration must contain only JSON-compatible values"
        raise ValueError(msg) from error
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
