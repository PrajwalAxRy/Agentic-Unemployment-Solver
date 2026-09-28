"""Deterministic adapter for Atlassian's same-origin public careers inventory."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpFailureCategory, HttpRequestError
from job_finder.core.job_contracts import DateBasis, NormalizedJob
from job_finder.core.source_contracts import (
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    AdapterType,
    CompanySource,
    DiagnosticSeverity,
)

ATLASSIAN_ADAPTER_KEY = "atlassian_careers_inventory"
ATLASSIAN_CAREERS_URL = "https://www.atlassian.com/company/careers/all-jobs"
ATLASSIAN_LISTINGS_URL = "https://www.atlassian.com/endpoint/careers/listings"

_UPDATED_DATE_FORMAT = "%Y-%m-%d %I:%M %p"
_ICIMS_PATH_PATTERN = re.compile(r"/jobs/([0-9]+)/[^/]+/job/?")
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
    "table",
    "td",
    "tr",
    "ul",
}


class AtlassianCareersAdapter:
    """Read Atlassian's complete collection and collapse intentional portal variants."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = ATLASSIAN_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                ATLASSIAN_LISTINGS_URL,
                accepted_content_types=("application/json",),
                referer=ATLASSIAN_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                _request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )
        if response.final_url.rstrip("/") != ATLASSIAN_LISTINGS_URL.rstrip("/"):
            return _failed(source, "unexpected_redirect", "Atlassian inventory redirected.")
        try:
            payload: Any = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _failed(source, "invalid_json", "Atlassian inventory was not valid JSON.")
        if not isinstance(payload, list):
            return _failed(
                source, "unsupported_schema", "Atlassian inventory root must be an array."
            )
        if not payload:
            return _failed(
                source,
                "unproved_empty_inventory",
                "Atlassian inventory exposed no independently proved empty-state contract.",
            )

        groups: dict[str, list[Mapping[str, object]]] = {}
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping):
                return _failed(
                    source,
                    "malformed_job",
                    f"Atlassian inventory row {index} must be an object.",
                )
            try:
                external_id = _positive_id(item.get("id"), "Atlassian job id")
            except ValueError as error:
                return _failed(source, "malformed_job", str(error))
            groups.setdefault(external_id, []).append(item)

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        missing_location_count = 0
        for index, variants in enumerate(groups.values()):
            try:
                job, missing_location = _normalize_variants(source, variants)
            except ValueError as error:
                diagnostics.append(
                    _diagnostic(
                        "malformed_job",
                        DiagnosticSeverity.ERROR,
                        str(error),
                        job_index=index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.PARTIAL if jobs else AdapterOutcome.FAILED,
                    jobs,
                    diagnostics,
                    page_count=1,
                )
            jobs.append(job)
            missing_location_count += int(missing_location)

        collapsed_count = len(payload) - len(jobs)
        if collapsed_count:
            diagnostics.append(
                _diagnostic(
                    "duplicate_portal_variants_collapsed",
                    DiagnosticSeverity.INFO,
                    "Atlassian duplicate portal variants were consistent and collapsed by job ID.",
                    count=collapsed_count,
                )
            )
        if missing_location_count:
            diagnostics.append(
                _diagnostic(
                    "missing_location",
                    DiagnosticSeverity.WARNING,
                    "Atlassian jobs without a public location remain explicitly unavailable.",
                    count=missing_location_count,
                )
            )
        diagnostics.append(
            _diagnostic(
                "unverified_updated_date",
                DiagnosticSeverity.WARNING,
                "Atlassian exposes an iCIMS updated date, not a verified publication date.",
                count=len(jobs),
            )
        )
        return _result(
            source,
            AdapterOutcome.SUCCESS,
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
    if parameters["adapter_key"] != ATLASSIAN_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Atlassian adapter requires adapter_key={ATLASSIAN_ADAPTER_KEY}."
        )
    if source.careers_url != ATLASSIAN_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Atlassian adapter requires careers_url={ATLASSIAN_CAREERS_URL}."
        )


def _normalize_variants(
    source: CompanySource,
    variants: list[Mapping[str, object]],
) -> tuple[NormalizedJob, bool]:
    if not variants:
        raise ValueError("Atlassian job group must not be empty.")
    first = variants[0]
    external_id = _positive_id(first.get("id"), "Atlassian job id")
    title = _required_string(first, "title", "Atlassian job")
    category = _required_string(first, "category", "Atlassian job")
    description_fields = _description_fields(first)
    updated_raw = _portal_updated_date(first, external_id)
    locations: list[str] = []
    portal_ids: list[int] = []

    for variant in variants:
        if _positive_id(variant.get("id"), "Atlassian job id") != external_id:
            raise ValueError("Atlassian grouped job identity changed across portal variants.")
        if _normalize_text(_required_string(variant, "title", "Atlassian job")) != _normalize_text(
            title
        ):
            raise ValueError("Atlassian portal variants disagree on title.")
        if _required_string(variant, "category", "Atlassian job") != category:
            raise ValueError("Atlassian portal variants disagree on category.")
        if _description_fields(variant) != description_fields:
            raise ValueError("Atlassian portal variants disagree on description.")
        if _portal_updated_date(variant, external_id) != updated_raw:
            raise ValueError("Atlassian portal variants disagree on updated date.")
        portal_id = _positive_int(variant.get("portalId"), "Atlassian portalId")
        portal_ids.append(portal_id)
        _validate_icims_url(
            _required_string(variant, "applyUrl", "Atlassian job"),
            external_id,
            "applyUrl",
        )
        raw_locations = variant.get("locations")
        if not isinstance(raw_locations, list):
            raise ValueError("Atlassian job locations must be an array.")
        for raw_location in raw_locations:
            if not isinstance(raw_location, str) or not raw_location.strip():
                raise ValueError("Atlassian job locations must contain non-empty strings.")
            normalized = _normalize_whitespace(raw_location)
            if normalized not in locations:
                locations.append(normalized)

    description = _combined_description(description_fields)
    if len(description) < 80:
        raise ValueError("Atlassian job description normalized to insufficient text.")
    try:
        updated_at = datetime.strptime(updated_raw, _UPDATED_DATE_FORMAT).date()
    except ValueError as error:
        raise ValueError("Atlassian updated date did not match the verified format.") from error
    missing_location = not locations
    location = " | ".join(locations) if locations else "location unavailable"
    return (
        NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=AdapterType.CUSTOM.value,
            external_job_id=external_id,
            title_original=_normalize_whitespace(title),
            title_normalized=_normalize_text(title),
            location_original=location,
            location_normalized=tuple(_normalize_text(item) for item in locations)
            or ("location unavailable",),
            published_at=updated_at,
            published_at_raw=updated_raw,
            date_basis=DateBasis.UNKNOWN,
            canonical_url=f"https://www.atlassian.com/company/careers/details/{external_id}",
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata={
                "adapter_key": ATLASSIAN_ADAPTER_KEY,
                "category": category,
                "portal_ids": tuple(sorted(set(portal_ids))),
                "updated_date_unverified": True,
                "missing_location": missing_location,
            },
        ),
        missing_location,
    )


def _portal_updated_date(raw: Mapping[str, object], external_id: str) -> str:
    portal = raw.get("portalJobPost")
    if not isinstance(portal, Mapping):
        raise ValueError("Atlassian job portalJobPost must be an object.")
    if _positive_id(portal.get("id"), "Atlassian portal job id") != external_id:
        raise ValueError("Atlassian portal job id does not match its top-level id.")
    top_portal_id = _positive_int(raw.get("portalId"), "Atlassian portalId")
    if _positive_int(portal.get("portalId"), "Atlassian portal job portalId") != top_portal_id:
        raise ValueError("Atlassian portalId fields disagree.")
    _validate_icims_url(
        _required_string(portal, "portalUrl", "Atlassian portal job"),
        external_id,
        "portalUrl",
    )
    return _required_string(portal, "updatedDate", "Atlassian portal job")


def _validate_icims_url(value: str, external_id: str, field: str) -> None:
    parsed = urlsplit(value)
    match = _ICIMS_PATH_PATTERN.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not parsed.hostname.endswith(".icims.com")
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or match is None
        or match.group(1) != external_id
    ):
        raise ValueError(f"Atlassian {field} must be an official iCIMS job URL.")


def _description_fields(raw: Mapping[str, object]) -> tuple[str, str, str, str]:
    compensation = raw.get("compensation")
    if compensation is None:
        compensation = ""
    if not isinstance(compensation, str):
        raise ValueError("Atlassian compensation must be text or null.")
    return (
        _required_string(raw, "overview", "Atlassian job"),
        _required_string(raw, "responsibilities", "Atlassian job"),
        _required_string(raw, "qualifications", "Atlassian job"),
        compensation,
    )


def _combined_description(fields: tuple[str, str, str, str]) -> str:
    sections = [_html_text(value) for value in fields if value.strip()]
    return "\n\n".join(section for section in sections if section)


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "svg", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif self.skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def _html_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    return "\n".join(
        line
        for line in (_normalize_whitespace(part) for part in "".join(parser.parts).splitlines())
        if line
    )


def _required_string(raw: Mapping[str, object], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} {field} must be a non-empty string.")
    return value.strip()


def _positive_id(value: object, context: str) -> str:
    return str(_positive_int(value, context))


def _positive_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{context} must be a positive integer.")
    return value


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text(value: str) -> str:
    return _normalize_whitespace(value).casefold()


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


def _failed(source: CompanySource, category: str, message: str) -> AdapterResult:
    return _result(
        source,
        AdapterOutcome.FAILED,
        [],
        [_diagnostic(category, DiagnosticSeverity.ERROR, message)],
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
