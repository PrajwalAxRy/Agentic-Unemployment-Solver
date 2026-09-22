"""Persistent job identity and evaluation state."""

from job_finder.persistence.database import (
    CURRENT_SCHEMA_VERSION,
    current_schema_version,
    migrate_database,
    migrated_database,
    open_database,
)
from job_finder.persistence.identity import (
    JobIdentity,
    JobIdentityStrategy,
    build_fallback_fingerprint,
    job_identity,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "JobIdentity",
    "JobIdentityStrategy",
    "build_fallback_fingerprint",
    "current_schema_version",
    "migrate_database",
    "migrated_database",
    "open_database",
    "job_identity",
]
