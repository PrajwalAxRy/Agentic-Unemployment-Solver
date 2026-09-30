"""Deterministic adapter for Gnani.ai's public careers API and detail pages."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from job_finder.adapters._support import diagnostic, request_outcome
from job_finder.adapters.base import (
    AdapterConfigurationError,
    request_failure_diagnostic,
    require_source_configuration,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpRequestError
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
from job_finder.core.validation import clean_optional, required_string
from job_finder.normalization.jobs import (
    normalize_source_locations as _shared_locations,
)
from job_finder.normalization.jobs import (
    normalize_text,
    normalize_title,
)

GNANI_ADAPTER_KEY = "gnani_careers_api"
GNANI_CAREERS_URL = "https://careers.gnani.ai/"
GNANI_JOBS_API = "https://careers.gnani.ai/api/jobs"

_HOST = "careers.gnani.ai"
_CODE_PATTERN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]*)+")
_DETAIL_PATH_PATTERN = re.compile(r"/apply/([A-Za-z0-9]+(?:-[A-Za-z0-9]*)+)")
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
    "main",
    "p",
    "section",
    "ul",
}
_SKIP_TAGS = {"script", "style", "svg", "noscript"}


class GnaniCareersAdapter:
    """Read Gnani.ai's complete public JSON collection and deferred details."""

    adapter_type = AdapterType.CUSTOM
    adapter_key = GNANI_ADAPTER_KEY

    def __init__(self, client: BoundedHttpClient | None = None) -> None:
        self._client = client or BoundedHttpClient()

    def list_jobs(self, source: CompanySource) -> AdapterResult:
        _validate_source(source)
        try:
            response = self._client.get(
                GNANI_JOBS_API,
                accepted_content_types=("application/json",),
                referer=GNANI_CAREERS_URL,
            )
        except HttpRequestError as error:
            return _result(
                source,
                request_outcome(error),
                [],
                [request_failure_diagnostic(error)],
                page_count=0,
            )

        if response.final_url != GNANI_JOBS_API:
            return _failed(source, "unexpected_redirect", "Gnani.ai jobs API redirected.")
        try:
            payload = json.loads(response.body)
            root = _required_mapping(payload, "Gnani.ai response")
            if root.get("success") is not True:
                raise ValueError("Gnani.ai jobs API did not report success=true.")
            data = _required_mapping(root.get("data"), "Gnani.ai response data")
            raw_jobs = _required_list(data.get("jobs"), "Gnani.ai jobs")
            total = data.get("total")
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                raise ValueError("Gnani.ai jobs total must be a non-negative integer.")
            if total != len(raw_jobs):
                raise ValueError("Gnani.ai jobs total does not match the returned collection.")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            return _failed(source, "unsupported_schema", str(error))

        jobs: list[NormalizedJob] = []
        diagnostics: list[AdapterDiagnostic] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(raw_jobs):
            try:
                job, used_remote_default = _normalize_job(source, raw)
            except ValueError as error:
                diagnostics.append(
                    diagnostic(
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
            external_id = job.external_job_id
            if external_id is None:
                raise AssertionError("Gnani.ai jobs require an external ID")
            if external_id in seen_ids:
                diagnostics.append(
                    diagnostic(
                        "duplicate_job_id",
                        DiagnosticSeverity.ERROR,
                        "Gnani.ai returned a duplicate job code.",
                        job_index=index,
                    )
                )
                return _result(
                    source,
                    AdapterOutcome.SUSPICIOUS,
                    jobs,
                    diagnostics,
                    page_count=1,
                )
            seen_ids.add(external_id)
            jobs.append(job)
            if used_remote_default:
                diagnostics.append(
                    diagnostic(
                        "null_location_is_remote",
                        DiagnosticSeverity.INFO,
                        "Gnani.ai renders a null API location as Remote.",
                        job_id=external_id,
                    )
                )

        return _result(
            source,
            AdapterOutcome.SUCCESS if jobs else AdapterOutcome.EMPTY,
            jobs,
            diagnostics,
            page_count=1,
            complete=True,
        )

    def get_job_detail(self, source: CompanySource, job: NormalizedJob) -> NormalizedJob:
        _validate_source(source)
        _validate_job(source, job)
        try:
            response = self._client.get(
                job.canonical_url,
                accepted_content_types=("text/html",),
                referer=GNANI_CAREERS_URL,
            )
        except HttpRequestError as error:
            raise ValueError(f"Gnani.ai detail request failed: {error.category.value}") from error
        if response.final_url.rstrip("/") != job.canonical_url.rstrip("/"):
            raise ValueError("Gnani.ai detail redirected outside its canonical URL.")
        document = _decode(response.body, "Gnani.ai detail")
        if is_access_block_html(document):
            raise ValueError("Gnani.ai detail returned an access-control page.")
        description = _detail_description(document, job)
        return replace(
            job,
            description=description,
            description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
            source_metadata={**job.source_metadata, "detail_retrieved": True},
        )


def _validate_source(source: CompanySource) -> None:
    parameters = require_source_configuration(
        source,
        adapter_type=AdapterType.CUSTOM,
        required_parameters=("adapter_key",),
    )
    if parameters["adapter_key"] != GNANI_ADAPTER_KEY:
        raise AdapterConfigurationError(
            f"Gnani.ai adapter requires adapter_key={GNANI_ADAPTER_KEY}."
        )
    if source.careers_url != GNANI_CAREERS_URL:
        raise AdapterConfigurationError(
            f"Gnani.ai adapter requires careers_url={GNANI_CAREERS_URL}."
        )


def _validate_job(source: CompanySource, job: NormalizedJob) -> None:
    if job.company_id != source.company_id or job.source_type != AdapterType.CUSTOM.value:
        raise AdapterConfigurationError("Gnani.ai detail job does not belong to the source.")
    canonical_url, external_id = _canonical_detail_url(job.canonical_url)
    if canonical_url != job.canonical_url or external_id != job.external_job_id:
        raise AdapterConfigurationError("Gnani.ai detail job identity is inconsistent.")


def _normalize_job(source: CompanySource, value: object) -> tuple[NormalizedJob, bool]:
    raw = _required_mapping(value, "Gnani.ai job")
    title = required_string(raw, "title", "Gnani.ai job")
    code = required_string(raw, "code", "Gnani.ai job")
    if _CODE_PATTERN.fullmatch(code) is None:
        raise ValueError("Gnani.ai job code has an unsupported format.")
    canonical_url, external_id = _canonical_detail_url(f"{GNANI_CAREERS_URL}apply/{code}")
    if external_id != code:
        raise ValueError("Gnani.ai job code does not match its canonical URL.")

    location_value = raw.get("location")
    used_remote_default = location_value is None
    if used_remote_default:
        location = "Remote"
    else:
        locations = _string_list(location_value, "Gnani.ai job location")
        if not locations:
            raise ValueError("Gnani.ai job location must not be an empty array.")
        location = ", ".join(locations)

    published_raw = required_string(raw, "positionPublishDate", "Gnani.ai job")
    try:
        published_at = datetime.strptime(published_raw, "%Y-%m-%d %H:%M:%S").date()
    except ValueError as error:
        raise ValueError("Gnani.ai positionPublishDate is invalid.") from error

    minimum = _non_negative_int(raw.get("minExperience"), "Gnani.ai minExperience")
    maximum = _non_negative_int(raw.get("maxExperience"), "Gnani.ai maxExperience")
    if minimum > maximum:
        raise ValueError("Gnani.ai minimum experience exceeds maximum experience.")
    vacancies = _positive_int(raw.get("vacancies"), "Gnani.ai vacancies")
    skills = tuple(_string_list(raw.get("skills"), "Gnani.ai skills"))
    department = clean_optional(raw.get("department"))
    designation = clean_optional(raw.get("designation"))
    return (
        NormalizedJob(
            schema_version=1,
            company_id=source.company_id,
            source_type=AdapterType.CUSTOM.value,
            external_job_id=code,
            title_original=title,
            title_normalized=normalize_title(title),
            location_original=location,
            location_normalized=_shared_locations(location),
            published_at=published_at,
            published_at_raw=published_raw,
            date_basis=DateBasis.PUBLISHED,
            canonical_url=canonical_url,
            description=None,
            description_hash=None,
            source_metadata={
                "adapter_key": GNANI_ADAPTER_KEY,
                "department": department,
                "designation": designation,
                "minimum_experience_years": minimum,
                "maximum_experience_years": maximum,
                "vacancies": vacancies,
                "skills": skills,
                "location_defaulted_from_null": used_remote_default,
            },
        ),
        used_remote_default,
    )


class _BodyTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "body":
            self.in_body = True
            return
        if not self.in_body:
            return
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "body":
            self.in_body = False
            return
        if not self.in_body:
            return
        if tag in _SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_body and self.skip_depth == 0:
            self.parts.append(data)


def _detail_description(document: str, job: NormalizedJob) -> str:
    parser = _BodyTextParser()
    parser.feed(document)
    parser.close()
    lines = _normalized_lines(parser.parts)
    if normalize_text(job.title_original) not in {normalize_text(line) for line in lines}:
        raise ValueError("Gnani.ai detail title does not match the listing.")
    start = next(
        (index for index, line in enumerate(lines) if line.casefold() == "responsibilities"),
        None,
    )
    if start is None:
        raise ValueError("Gnani.ai detail has no Responsibilities section.")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].casefold() in {"apply", "submit your application"}
        ),
        None,
    )
    if end is None:
        raise ValueError("Gnani.ai detail has no application boundary.")
    description = "\n\n".join(lines[start:end]).strip()
    if len(description) < 80:
        raise ValueError("Gnani.ai detail description normalized to insufficient text.")
    return description


def _canonical_detail_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    match = _DETAIL_PATH_PATTERN.fullmatch(parsed.path.rstrip("/"))
    if (
        parsed.scheme != "https"
        or parsed.hostname != _HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("Gnani.ai job URL must be a canonical same-origin /apply/<code> URL.")
    code = match.group(1)
    return f"https://{_HOST}/apply/{code}", code


def _decode(body: bytes, context: str) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{context} was not valid UTF-8.") from error


def _normalized_lines(parts: Iterable[str]) -> list[str]:
    text = "".join(parts).replace("\r", "")
    return [
        normalized
        for line in text.splitlines()
        if (normalized := re.sub(r"\s+", " ", line).strip())
    ]


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain only non-empty strings.")
        normalized = re.sub(r"\s+", " ", item).strip()
        if normalized not in result:
            result.append(normalized)
    return result


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


def _positive_int(value: object, field: str) -> int:
    result = _non_negative_int(value, field)
    if result == 0:
        raise ValueError(f"{field} must be positive.")
    return result


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
