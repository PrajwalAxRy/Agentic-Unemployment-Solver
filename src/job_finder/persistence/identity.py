"""Stable, source-aware job identity mapping."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from job_finder.core.job_contracts import NormalizedJob
from job_finder.normalization.jobs import canonicalize_job_url, normalize_text, normalize_title


class JobIdentityStrategy(StrEnum):
    """Identity evidence used to construct a stable job key."""

    EXTERNAL_ID = "external_id"
    CANONICAL_URL = "canonical_url"
    FALLBACK_FINGERPRINT = "fallback_fingerprint"


@dataclass(frozen=True, slots=True)
class JobIdentity:
    """Stable identity values persisted for one normalized posting."""

    job_key: str
    strategy: JobIdentityStrategy
    canonical_url: str
    fallback_fingerprint: str


def job_identity(job: NormalizedJob) -> JobIdentity:
    """Build a job key using external ID, canonical URL, then fallback fingerprint."""
    canonical_url = canonicalize_job_url(job.canonical_url)
    fallback_fingerprint = build_fallback_fingerprint(
        company_id=job.company_id,
        title=job.title_normalized,
        locations=job.location_normalized,
        team=_metadata_text(job, "team"),
        department=_metadata_text(job, "department"),
    )
    external_job_id = _optional_identity_text(job.external_job_id)
    if external_job_id is not None:
        strategy = JobIdentityStrategy.EXTERNAL_ID
        identity_value = _digest(
            {
                "company_id": job.company_id,
                "external_job_id": external_job_id,
                "source_type": job.source_type,
            }
        )
    elif canonical_url:
        strategy = JobIdentityStrategy.CANONICAL_URL
        identity_value = _digest(
            {
                "canonical_url": canonical_url,
                "company_id": job.company_id,
            }
        )
    else:  # pragma: no cover - NormalizedJob currently requires a canonical URL.
        strategy = JobIdentityStrategy.FALLBACK_FINGERPRINT
        identity_value = fallback_fingerprint

    return JobIdentity(
        job_key=f"v1:{strategy.value}:{identity_value}",
        strategy=strategy,
        canonical_url=canonical_url,
        fallback_fingerprint=fallback_fingerprint,
    )


def build_fallback_fingerprint(
    *,
    company_id: str,
    title: str,
    locations: tuple[str, ...],
    team: str | None = None,
    department: str | None = None,
) -> str:
    """Hash conservative normalized fields used only when stronger identity is unavailable."""
    normalized_locations = sorted(
        {normalize_text(location).casefold() for location in locations if normalize_text(location)}
    )
    if not normalized_locations:
        raise ValueError("fallback identity requires at least one location")
    return _digest(
        {
            "company_id": normalize_text(company_id),
            "department": _optional_fallback_text(department),
            "locations": normalized_locations,
            "team": _optional_fallback_text(team),
            "title": normalize_title(title),
        }
    )


def _metadata_text(job: NormalizedJob, key: str) -> str | None:
    value = job.source_metadata.get(key)
    return value if isinstance(value, str) else None


def _optional_identity_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(value)
    return normalized or None


def _optional_fallback_text(value: str | None) -> str | None:
    normalized = _optional_identity_text(value)
    return normalized.casefold() if normalized is not None else None


def _digest(content: dict[str, object]) -> str:
    canonical = json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
