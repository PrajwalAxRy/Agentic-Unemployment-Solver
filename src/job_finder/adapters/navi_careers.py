"""Deterministic adapter for Navi's complete public careers API."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit, urlunsplit

from job_finder.adapters._support import diagnostic, request_outcome
from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpRequestError
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    DiagnosticSeverity,
)
from job_finder.core.validation import required_string
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_title,
)

NAVI_ADAPTER_KEY = "navi_public_careers_api"
NAVI_CAREERS_URL = "https://navi.com/careers/jobs"
NAVI_JOBS_API = "https://navi.com/api/careers/jobs"
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_BLOCK_TAGS = {
    "article",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "section",
    "ul",
}


class NaviCareersAdapter:
    """Retrieve and reconcile Navi's one-response public job collection."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = NAVI_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                NAVI_JOBS_API,
                accepted_content_types=("application/json",),
                referer=NAVI_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url != NAVI_JOBS_API:
            return _failed(source, "unexpected_redirect", "Navi jobs API redirected.")
        try:
            root = _required_mapping(json.loads(response.body), "Navi response")
            total = _non_negative_int(root.get("Total"), "Navi Total")
            filtered = _non_negative_int(root.get("FilteredCount"), "Navi FilteredCount")
            raw_jobs = _required_list(root.get("Jobs"), "Navi Jobs")
            if total != filtered or total != len(raw_jobs):
                raise ValueError("Navi totals do not match the returned Jobs collection.")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            return _failed(source, "unsupported_schema", str(error))

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        parse_error_count = 0
        for index, raw_job in enumerate(raw_jobs):
            try:
                job = _normalize_job(source, raw_job)
            except (json.JSONDecodeError, ValueError) as error:
                # Skip the offending row and keep going, matching greenhouse.py and
                # ashby.py. Returning here made one unparseable row discard every later
                # job in the response: the 2026-10-01 run kept 4 of 36 because the 5th
                # row carried an unexpected legal entity name. One bad row is a row-level
                # fact, so the completeness signal below -- not an early return -- is what
                # reports it.
                parse_error_count += 1
                diagnostics.append(
                    diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=index,
                    )
                )
                continue
            external_id = job.external_job_id
            if external_id is None:
                raise AssertionError("Navi jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Navi returned a duplicate JobId.",
                        job_index=index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, diagnostics, page_count=1)
            seen_ids.add(external_id)
            jobs.append(job)

        if parse_error_count:
            # Still fail closed on completeness: we reconciled Total against the returned
            # collection, but we could not normalize every row, so this is not a complete
            # view of the source and must not be recorded as one. Zero surviving rows is a
            # whole-source fault, not a partial read -- a schema change or a renamed entity
            # fails every row, and reporting that as PARTIAL with no jobs would present
            # total loss as a successful partial read.
            return _result(
                source,
                AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                jobs,
                diagnostics,
                page_count=1,
            )

        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            diagnostics,
            page_count=1,
            complete=True,
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != NAVI_ADAPTER_KEY:
        raise AdapterConfigurationError(f"Navi adapter requires adapter_key={NAVI_ADAPTER_KEY}.")
    if source.careers_url != NAVI_CAREERS_URL:
        raise AdapterConfigurationError(f"Navi adapter requires careers_url={NAVI_CAREERS_URL}.")


def _normalize_job(source: CompanySource, value: object) -> NormalizedJob:
    raw = _required_mapping(value, "Navi job")
    external_id = required_string(raw, "JobId", "Navi job")
    if _UUID_PATTERN.fullmatch(external_id) is None:
        raise ValueError("Navi JobId must be a UUID.")
    company_name = required_string(raw, "CompanyName", "Navi job")
    if not _is_navi_entity(company_name):
        raise ValueError(
            f"Navi job CompanyName did not identify a Navi group entity: {company_name!r}"
        )
    title = required_string(raw, "JobTitle", "Navi job")
    canonical_url = _job_url(required_string(raw, "ApplyUrl", "Navi job"), external_id)
    location_raw = required_string(raw, "Location", "Navi job")
    locations = _location_values(location_raw)
    description_html = required_string(raw, "JobDescriptionV2", "Navi job")
    description = _plain_text(description_html)
    if not description:
        raise ValueError("Navi JobDescriptionV2 normalized to empty text.")
    published_raw = required_string(raw, "PublishedDate", "Navi job")
    published_at = _timestamp(published_raw, "Navi PublishedDate")
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id.casefold(),
        title_original=title,
        title_normalized=normalize_title(title),
        location_original=" | ".join(locations),
        location_normalized=_shared_locations(locations),
        published_at=published_at,
        published_at_raw=published_raw,
        date_basis=DateBasis.PUBLISHED,
        canonical_url=canonical_url,
        description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        source_metadata={
            "adapter_key": NAVI_ADAPTER_KEY,
            "company_name": company_name,
            "job_code": required_string(raw, "JobCode", "Navi job"),
            "department": required_string(raw, "Department", "Navi job"),
            "job_type": required_string(raw, "JobType", "Navi job"),
        },
    )


def _is_navi_entity(value: str) -> bool:
    """Accept any Navi group legal entity, not a fixed pair of display names.

    The public API returns the *legal* entity that owns each requisition, and the group
    posts under several: ``Navi Limited`` (the renamed holding company) alongside
    ``NAVI TECHNOLOGIES LIMITED``, its former name, which still owns live requisitions.
    A fixed allowlist of two exact strings treated the second as a malformed job and
    aborted the whole source (2026-10-01 run: 4 of 36 jobs, collection stopped at the
    first one). Entity names change with corporate action; the title filter is the
    component that decides relevance, so this check only needs to prove the posting
    belongs to Navi rather than to an unrelated company sharing the endpoint.

    The first word must be exactly ``navi`` so that a different company whose name merely
    contains the substring (``Navigator Systems``, ``NaviLink``) is still rejected.

    Empty tokens are dropped before that check so the result does not depend on the
    caller having stripped the value first: leading punctuation (``"Navi" Ltd``) would
    otherwise put ``""`` in front and reject a genuine entity.
    """
    tokens = [token for token in re.split(r"[^a-z0-9]+", value.casefold()) if token]
    return bool(tokens) and tokens[0] == "navi"


def _location_values(value: str) -> list[str]:
    payload = json.loads(value)
    items = _required_list(payload, "Navi Location JSON")
    locations: list[str] = []
    for item in items:
        raw = _required_mapping(item, "Navi Location item")
        address = required_string(raw, "Address", "Navi Location item")
        if address not in locations:
            locations.append(address)
    if not locations:
        raise ValueError("Navi Location JSON must contain at least one address.")
    return locations


def _job_url(value: str, external_id: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "navi.turbohire.co"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != f"/job/publicjobs/{external_id}"
        or parse_qs(parsed.query) != {"utm_source": ["CareerPage"]}
        or parsed.fragment
    ):
        raise ValueError("Navi ApplyUrl did not match its JobId.")
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), parsed.query, ""))


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(html.unescape(value))
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _required_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array.")
    return value


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer.")
    return value


def _failed(source: CompanySource, category: str, message: str) -> AdapterResult:
    return _result(
        source,
        AdapterOutcome.FAILED,
        [],
        [diagnostic(category, DiagnosticSeverity.ERROR, message)],
        page_count=1,
    )


def _result(
    source: CompanySource,
    outcome: AdapterOutcome,
    jobs: list[NormalizedJob],
    diagnostics: list[AdapterDiagnostic],
    *,
    page_count: int,
    complete: bool = False,
) -> AdapterResult:
    return AdapterResult(
        schema_version=1,
        source=source,
        outcome=outcome,
        jobs=tuple(jobs),
        page_count=page_count,
        complete=complete,
        diagnostics=tuple(diagnostics),
    )
