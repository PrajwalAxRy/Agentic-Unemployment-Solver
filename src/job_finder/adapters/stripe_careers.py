"""Deterministic adapter for Stripe's public embedded careers index."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.errors import DetailContentMissing, DetailIdentityMismatch
from job_finder.adapters.http_client import BoundedHttpClient, HttpFailureCategory, HttpRequestError
from job_finder.core.access_detection import is_access_block_html
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    DiagnosticSeverity,
)

STRIPE_CAREERS_ADAPTER_KEY = "stripe_careers_index"
STRIPE_CAREERS_URL = "https://stripe.com/careers/search"

_STRIPE_HOST = "stripe.com"
_SEARCH_PATH = "/careers/search"
_DETAIL_PATH_PATTERN = re.compile(r"/careers/listing/([a-z0-9][a-z0-9-]*)/([0-9]+)/?")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^\)]+\)")


class StripeCareersAdapter:
    """Retrieve Stripe's complete embedded index and deferred public details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = STRIPE_CAREERS_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                STRIPE_CAREERS_URL,
                accepted_content_types=("text/html",),
                referer=STRIPE_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                0,
                [request_failure_diagnostic(error)],
            )
        try:
            response_url = _canonical_search_url(response.final_url)
        except ValueError:
            response_url = None
        if response_url != STRIPE_CAREERS_URL:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "unexpected_redirect",
                        DiagnosticSeverity.ERROR,
                        "Stripe careers redirected outside the approved search page.",
                    )
                ],
            )
        document = _decode_document(response.body)
        if document is None:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [
                    _diagnostic(
                        "invalid_encoding",
                        DiagnosticSeverity.ERROR,
                        "Stripe careers search was not valid UTF-8.",
                    )
                ],
            )
        if is_access_block_html(document):
            block_error = HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
            return _result(
                source,
                AdapterOutcome.BLOCKED,
                [],
                1,
                [request_failure_diagnostic(block_error)],
            )
        try:
            payload = _next_data(document)
            index = _stripe_index(payload)
            filters = _required_mapping(index.get("filters"), "Stripe job index filters")
            locations = _object_list(filters, "locations")
            teams = _object_list(filters, "teams")
            tags = _object_list(filters, "tags")
            listings = _object_list(index, "listings")
        except (KeyError, TypeError, ValueError) as error:
            return _result(
                source,
                AdapterOutcome.FAILED,
                [],
                1,
                [_diagnostic("unsupported_schema", DiagnosticSeverity.ERROR, str(error))],
            )

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        for job_index, raw in enumerate(listings):
            try:
                job = _normalize_listing(
                    source,
                    raw,
                    locations=locations,
                    teams=teams,
                    tags=tags,
                )
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=job_index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    1,
                    diagnostics,
                )
            external_id = job.external_job_id
            if external_id is None:
                raise AssertionError("Stripe normalized jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    _diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Stripe careers index returned a duplicate Greenhouse ID.",
                        job_index=job_index,
                    )
                )
                return _result(source, AdapterOutcome.SUSPICIOUS, jobs, 1, diagnostics)
            seen_ids.add(external_id)
            jobs.append(job)

        if jobs:
            diagnostics.append(
                _diagnostic(
                    "publication_date_requires_detail",
                    DiagnosticSeverity.WARNING,
                    "Stripe publication dates are available only on public detail pages.",
                    count=len(jobs),
                )
            )
        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            1,
            diagnostics,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        """Retrieve one Stripe detail page and preserve the listing identity."""
        _validate_source(source)
        if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
            raise DetailIdentityMismatch("Stripe detail job does not match the configured source.")
        canonical_url, slug, external_id = _canonical_detail_url(job.canonical_url)
        if canonical_url != job.canonical_url or external_id != job.external_job_id:
            raise DetailIdentityMismatch("Stripe detail URL identity does not match the listing.")

        response = self._client.get(
            canonical_url,
            accepted_content_types=("text/html",),
            referer=STRIPE_CAREERS_URL,
        )
        document = response.body.decode("utf-8")
        if is_access_block_html(document):
            raise HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "access-control or login page detected",
                status_code=response.status_code,
            )
        response_url, response_slug, response_id = _canonical_detail_url(response.final_url)
        if response_url != canonical_url or response_slug != slug or response_id != external_id:
            raise DetailIdentityMismatch("Stripe detail response URL does not match the listing.")

        payload = _next_data(document)
        props = _required_mapping(payload.get("props"), "Stripe props")
        page_props = _required_mapping(props.get("pageProps"), "Stripe pageProps")
        detail = _required_mapping(page_props.get("listing"), "Stripe detail listing")
        detail_id = _numeric_id(detail.get("greenhouseId"), "Stripe detail greenhouseId")
        detail_slug = _required_string(detail, "slug", "Stripe detail listing")
        detail_title = _required_string(detail, "title", "Stripe detail listing")
        if detail_id != external_id or detail_slug != slug:
            raise DetailIdentityMismatch(
                "Stripe detail payload identity does not match the listing."
            )
        if _normalize_text(detail_title) != job.title_normalized:
            raise DetailIdentityMismatch("Stripe detail title does not match the listing title.")
        detail_location_indices = tuple(
            _index_list(detail.get("locationIndices"), "Stripe detail locationIndices")
        )
        listing_location_indices = job.source_metadata.get("location_indices")
        if not isinstance(listing_location_indices, tuple) or any(
            not isinstance(item, int) for item in listing_location_indices
        ):
            raise DetailContentMissing("Stripe listing metadata omitted valid location indices.")
        if detail_location_indices != listing_location_indices:
            raise DetailIdentityMismatch("Stripe detail locations do not match the listing.")
        content_markdown = _required_string(detail, "contentMarkdown", "Stripe detail listing")
        description = _plain_markdown(content_markdown)
        if not description:
            raise DetailContentMissing("Stripe detail description normalized to empty text.")
        date_raw = _job_posting_date(document, external_id, detail_title, canonical_url)
        published_at = _iso_datetime(date_raw, "Stripe datePosted")
        metadata = dict(job.source_metadata)
        metadata["date_posted"] = date_raw
        return replace(
            job,
            published_at=published_at,
            published_at_raw=date_raw,
            date_basis=DateBasis.PUBLISHED,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata=metadata,
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != STRIPE_CAREERS_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Stripe adapter requires adapter_key={STRIPE_CAREERS_ADAPTER_KEY}"
        )
    if source.careers_url != STRIPE_CAREERS_URL:
        raise AdapterConfigurationError(f"Stripe adapter requires careers_url={STRIPE_CAREERS_URL}")


def _normalize_listing(
    source: CompanySource,
    value: object,
    *,
    locations: list[object],
    teams: list[object],
    tags: list[object],
) -> NormalizedJob:
    raw = _required_mapping(value, "Stripe listing")
    external_id = _numeric_id(raw.get("greenhouseId"), "Stripe greenhouseId")
    title = _required_string(raw, "title", "Stripe listing")
    slug = _required_string(raw, "slug", "Stripe listing")
    canonical_url, canonical_slug, canonical_id = _canonical_detail_url(
        f"https://{_STRIPE_HOST}/careers/listing/{slug}/{external_id}"
    )
    if canonical_slug != slug or canonical_id != external_id:
        raise ValueError("Stripe listing slug or ID was invalid.")
    location_indices = _index_list(raw.get("locationIndices"), "Stripe locationIndices")
    location_names = _indexed_names(location_indices, locations, "Stripe locations")
    if not location_names:
        raise ValueError("Stripe listing must contain at least one location.")
    team_indices = _index_list(raw.get("teamIndices", []), "Stripe teamIndices")
    tag_indices = _index_list(raw.get("tagIndices", []), "Stripe tagIndices")
    team_names = _indexed_names(team_indices, teams, "Stripe teams")
    tag_names = _indexed_names(tag_indices, tags, "Stripe tags")
    location = " | ".join(location_names)
    employment_type = _optional_string(raw.get("employmentType"))
    return NormalizedJob(
        schema_version=1,
        company_id=source.company_id,
        source_type=AdapterType.CUSTOM.value,
        external_job_id=external_id,
        title_original=title,
        title_normalized=_normalize_text(title),
        location_original=location,
        location_normalized=_normalized_locations(location),
        published_at=None,
        published_at_raw=None,
        date_basis=DateBasis.UNKNOWN,
        canonical_url=canonical_url,
        description=None,
        description_hash=None,
        source_metadata={
            "adapter_key": STRIPE_CAREERS_ADAPTER_KEY,
            "location_indices": tuple(location_indices),
            "teams": tuple(team_names),
            "tags": tuple(tag_names),
            "employment_type": employment_type,
        },
    )


class _ScriptDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.current_kind: str | None = None
        self.current_parts: list[str] = []
        self.next_data_blocks: list[str] = []
        self.json_ld_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "script":
            return
        attributes = {key.casefold(): value for key, value in attrs}
        if attributes.get("id") == "__NEXT_DATA__":
            self.current_kind = "next"
            self.current_parts = []
        elif (attributes.get("type") or "").casefold() == "application/ld+json":
            self.current_kind = "ld"
            self.current_parts = []

    def handle_data(self, data: str) -> None:
        if self.current_kind is not None:
            self.current_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script" or self.current_kind is None:
            return
        value = "".join(self.current_parts).strip()
        if self.current_kind == "next":
            self.next_data_blocks.append(value)
        else:
            self.json_ld_blocks.append(value)
        self.current_kind = None
        self.current_parts = []


def _script_blocks(document: str) -> _ScriptDataParser:
    parser = _ScriptDataParser()
    parser.feed(document)
    parser.close()
    return parser


def _next_data(document: str) -> Mapping[object, object]:
    parser = _script_blocks(document)
    if len(parser.next_data_blocks) != 1:
        raise ValueError("Stripe page must contain exactly one __NEXT_DATA__ block.")
    try:
        payload = json.loads(parser.next_data_blocks[0])
    except json.JSONDecodeError as error:
        raise ValueError("Stripe __NEXT_DATA__ block was not valid JSON.") from error
    return _required_mapping(payload, "Stripe __NEXT_DATA__")


def _stripe_index(payload: Mapping[object, object]) -> Mapping[object, object]:
    if payload.get("page") != "/careers/search":
        raise ValueError("Stripe search page identifier was unexpected.")
    props = _required_mapping(payload.get("props"), "Stripe props")
    page_props = _required_mapping(props.get("pageProps"), "Stripe pageProps")
    return _required_mapping(page_props.get("jobIndexData"), "Stripe jobIndexData")


def _job_posting_date(
    document: str,
    external_id: str,
    title: str,
    canonical_url: str,
) -> str:
    parser = _script_blocks(document)
    matches: list[str] = []
    for block in parser.json_ld_blocks:
        try:
            raw = json.loads(block)
        except json.JSONDecodeError:
            continue
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            if not isinstance(value, Mapping) or value.get("@type") != "JobPosting":
                continue
            identifier = value.get("identifier")
            identifier_value = identifier.get("value") if isinstance(identifier, Mapping) else None
            if (
                str(identifier_value) == external_id
                and _normalize_text(str(value.get("title", ""))) == _normalize_text(title)
                and value.get("url") == canonical_url
            ):
                date_posted = value.get("datePosted")
                if isinstance(date_posted, str) and date_posted.strip():
                    matches.append(date_posted.strip())
    if len(matches) != 1:
        raise ValueError("Stripe detail must contain one matching JobPosting datePosted value.")
    return matches[0]


def _canonical_search_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _STRIPE_HOST
        or parsed.port is not None
        or parsed.path.rstrip("/") != _SEARCH_PATH
        or parsed.query
    ):
        raise ValueError("Stripe search URL was not the approved canonical page.")
    return STRIPE_CAREERS_URL


def _canonical_detail_url(value: str) -> tuple[str, str, str]:
    parsed = urlsplit(value)
    match = _DETAIL_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _STRIPE_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("Stripe job URL must be an official slug and numeric ID path.")
    slug, external_id = match.groups()
    return f"https://{_STRIPE_HOST}{parsed.path.rstrip('/')}", slug, external_id


def _plain_markdown(value: str) -> str:
    lines: list[str] = []
    for raw_line in html.unescape(value).replace("\r", "").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        line = _MARKDOWN_LINK_PATTERN.sub(r"\1", line)
        line = re.sub(r"[*_`]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _iso_datetime(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp.") from error
    if result.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return result


def _indexed_names(indices: list[int], values: list[object], context: str) -> list[str]:
    names: list[str] = []
    for index in indices:
        if index >= len(values):
            raise ValueError(f"{context} index was outside the filter array.")
        item = _required_mapping(values[index], f"{context} item")
        names.append(_required_string(item, "name", f"{context} item"))
    return _unique_strings(names)


def _index_list(value: object, field: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array.")
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in value):
        raise ValueError(f"{field} must contain non-negative integers.")
    result = list(value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must not contain duplicates.")
    return result


def _numeric_id(value: object, field: str) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer.")
    return str(value)


def _required_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object.")
    return value


def _object_list(raw: Mapping[object, object], key: str) -> list[object]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"Stripe field {key} must be an array.")
    return value


def _required_string(raw: Mapping[object, object], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} field {key} must be a non-empty string.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _decode_document(body: bytes) -> str | None:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalized_locations(value: str) -> tuple[str, ...]:
    return tuple(
        _unique_strings(
            _normalize_text(piece) for piece in re.split(r"[,|;/]", value) if piece.strip()
        )
    )


def _unique_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        key = value.casefold()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _request_outcome(error: HttpRequestError) -> AdapterOutcome:
    return (
        AdapterOutcome.BLOCKED
        if error.category is HttpFailureCategory.ACCESS_BLOCK
        else AdapterOutcome.FAILED
    )


def _diagnostic(
    category: str,
    severity: DiagnosticSeverity,
    message: str,
    **context: object,
) -> AdapterDiagnostic:
    return AdapterDiagnostic(
        category=category,
        severity=severity,
        message=message,
        context={key: str(value) for key, value in context.items()},
    )


def _result(
    source: CompanySource,
    outcome: AdapterOutcome,
    jobs: list[NormalizedJob],
    page_count: int,
    diagnostics: list[AdapterDiagnostic],
    *,
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
