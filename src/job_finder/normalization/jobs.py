"""Shared normalization for comparable jobs from every adapter family."""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.search_profile import LocationPolicy

_WHITESPACE = re.compile(r"\s+")
_TITLE_PUNCTUATION = re.compile(r"[^\w+#]+", re.UNICODE)
_LOCATION_SEPARATOR = re.compile(r"\s*(?:[;|•]|\r?\n|\s/\s)\s*")
_TRACKING_QUERY_KEYS = frozenset(
    {
        "gh_src",
        "lever-source",
        "ref",
        "referrer",
        "source",
        "src",
        "trackingid",
        "trk",
    }
)
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
)


def normalize_text(value: str) -> str:
    """Normalize Unicode, HTML entities, punctuation variants, and whitespace."""
    decoded = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", decoded).translate(_PUNCTUATION_TRANSLATION)
    return _WHITESPACE.sub(" ", normalized).strip()


def normalize_title(value: str) -> str:
    """Produce a stable case-insensitive title string suitable for deterministic matching."""
    normalized = normalize_text(value).casefold()
    return _WHITESPACE.sub(" ", _TITLE_PUNCTUATION.sub(" ", normalized)).strip()


def normalize_location_values(
    values: str | Iterable[str],
    *,
    policy: LocationPolicy,
) -> tuple[str, ...]:
    """Normalize multi-location strings and configured city and region aliases."""
    raw_values = (values,) if isinstance(values, str) else tuple(values)
    locations: list[str] = []
    for raw_value in raw_values:
        for part in _LOCATION_SEPARATOR.split(normalize_text(raw_value)):
            normalized = _normalize_location(part, policy=policy)
            if normalized and normalized not in locations:
                locations.append(normalized)
    return tuple(locations)


def canonicalize_job_url(url: str) -> str:
    """Remove recognized tracking data while preserving job-identity parameters."""
    parsed = urlsplit(normalize_text(url))
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if not scheme or not hostname:
        raise ValueError("job URL must be absolute")

    port = parsed.port
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    netloc = f"{hostname}:{port}" if include_port else hostname
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_query_key(key)
    ]
    return urlunsplit((scheme, netloc, parsed.path or "/", urlencode(query_pairs), ""))


def parse_source_timestamp(value: object) -> datetime | date | None:
    """Parse exact source timestamps without inventing timezone or date precision."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, date):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return _parse_epoch(float(value))
    if not isinstance(value, str):
        return None

    raw = normalize_text(value)
    if not raw:
        return None
    if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        try:
            return _parse_epoch(float(raw))
        except ValueError:
            return None

    iso_value = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed_datetime = datetime.fromisoformat(iso_value)
    except ValueError:
        parsed_datetime = None
    if parsed_datetime is not None:
        if parsed_datetime.tzinfo is None:
            if "T" in raw or " " in raw:
                return None
            return parsed_datetime.date()
        return parsed_datetime

    for pattern in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def normalize_job(job: NormalizedJob, *, location_policy: LocationPolicy) -> NormalizedJob:
    """Apply shared normalization while retaining source-original fields and evidence."""
    parsed_date = parse_source_timestamp(job.published_at)
    if parsed_date is None and job.published_at is None:
        parsed_date = parse_source_timestamp(job.published_at_raw)
    locations = normalize_location_values(job.location_original, policy=location_policy)
    if not locations:
        locations = tuple(normalize_text(value).casefold() for value in job.location_normalized)
    return replace(
        job,
        title_normalized=normalize_title(job.title_original),
        location_normalized=locations,
        published_at=parsed_date,
        canonical_url=canonicalize_job_url(job.canonical_url),
    )


def _normalize_location(value: str, *, policy: LocationPolicy) -> str:
    normalized = normalize_text(value).casefold()
    aliases: dict[str, str] = {}
    _add_aliases(aliases, policy.city_aliases)
    _add_aliases(aliases, policy.region_aliases)
    for alias in sorted(aliases, key=len, reverse=True):
        normalized = re.sub(
            rf"(?<!\w){re.escape(alias)}(?!\w)",
            aliases[alias],
            normalized,
            flags=re.IGNORECASE,
        )
    normalized = _TITLE_PUNCTUATION.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def _add_aliases(target: dict[str, str], groups: Mapping[str, tuple[str, ...]]) -> None:
    for canonical, values in groups.items():
        canonical_value = normalize_text(canonical).casefold()
        target[canonical_value] = canonical_value
        for value in values:
            target[normalize_text(value).casefold()] = canonical_value


def _is_tracking_query_key(key: str) -> bool:
    normalized = key.casefold()
    return normalized.startswith("utm_") or normalized in _TRACKING_QUERY_KEYS


def _parse_epoch(value: float) -> datetime | None:
    seconds = value / 1000 if abs(value) >= 100_000_000_000 else value
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
