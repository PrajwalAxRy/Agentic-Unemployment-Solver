"""Source-independent normalized job contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from job_finder.core.public_urls import validate_public_http_url

SUPPORTED_NORMALIZED_JOB_SCHEMA_VERSION = 1


class DateBasis(StrEnum):
    """Meaning of the source date attached to a job."""

    PUBLISHED = "published"
    UPDATED = "updated"
    FIRST_SEEN = "first_seen"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class NormalizedJob:
    """Common job record emitted by every adapter."""

    schema_version: int
    company_id: str
    source_type: str
    external_job_id: str | None
    title_original: str
    title_normalized: str
    location_original: str
    location_normalized: tuple[str, ...]
    published_at: datetime | date | None
    published_at_raw: str | None
    date_basis: DateBasis
    canonical_url: str
    description: str | None = None
    description_hash: str | None = None
    source_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SUPPORTED_NORMALIZED_JOB_SCHEMA_VERSION:
            raise ValueError(
                "unsupported normalized job schema_version: "
                f"{self.schema_version}; supported={SUPPORTED_NORMALIZED_JOB_SCHEMA_VERSION}"
            )
        for path, value in (
            ("company_id", self.company_id),
            ("source_type", self.source_type),
            ("title_original", self.title_original),
            ("title_normalized", self.title_normalized),
            ("location_original", self.location_original),
        ):
            if not value.strip():
                raise ValueError(f"normalized job {path} must be non-empty")
        if not self.location_normalized or any(
            not location.strip() for location in self.location_normalized
        ):
            raise ValueError("normalized job location_normalized must contain non-empty values")
        validate_public_http_url(self.canonical_url, "normalized job canonical_url")
        if isinstance(self.published_at, datetime) and self.published_at.tzinfo is None:
            raise ValueError("normalized job published_at datetime must be timezone-aware")
        if self.description_hash is not None and self.description is None:
            raise ValueError("description_hash requires a description")
