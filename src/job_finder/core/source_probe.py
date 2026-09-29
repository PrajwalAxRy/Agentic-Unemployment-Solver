"""Bounded, read-only HTTP probes for provisional source verification."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from job_finder.core.access_detection import extract_html_title, is_access_block_html
from job_finder.core.public_urls import PublicUrlRedirectHandler, validate_public_http_url

MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "job-finder-source-discovery/0.1 (manual public job-source verification)"


class ProbeOutcome(StrEnum):
    """Sanitized result category for one public URL probe."""

    SUCCESS = "success"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    ACCESS_BLOCK = "access_block"
    INVALID_CONTENT = "invalid_content"
    RESPONSE_TOO_LARGE = "response_too_large"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Safe-to-store metadata from one request, without response content."""

    requested_url: str
    final_url: str | None
    outcome: ProbeOutcome
    status_code: int | None
    content_type: str | None
    redirect_count: int
    page_title: str | None
    job_count: int | None
    detail: str

    def as_json(self) -> dict[str, object]:
        data = asdict(self)
        data["outcome"] = self.outcome.value
        return data


def probe_public_url(
    url: str,
    *,
    expect_json_jobs: bool,
    timeout_seconds: float = 12.0,
    retry_count: int = 1,
) -> ProbeResult:
    """Probe one public URL with bounded reads and one optional transient retry."""
    for attempt in range(retry_count + 1):
        result = _probe_once(
            url, expect_json_jobs=expect_json_jobs, timeout_seconds=timeout_seconds
        )
        if result.status_code not in {429, 500, 502, 503, 504} or attempt == retry_count:
            return result
        time.sleep(min(1.0 * (attempt + 1), 2.0))
    raise AssertionError("unreachable retry loop")


def _probe_once(url: str, *, expect_json_jobs: bool, timeout_seconds: float) -> ProbeResult:
    try:
        validate_public_http_url(url, "probe URL")
    except ValueError:
        return _failure(url, ProbeOutcome.ACCESS_BLOCK, "probe URL is not public HTTP or HTTPS")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        opener = urllib.request.build_opener(PublicUrlRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:
            status_code = response.status
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        return ProbeResult(
            requested_url=url,
            final_url=error.geturl(),
            outcome=ProbeOutcome.HTTP_ERROR,
            status_code=error.code,
            content_type=error.headers.get_content_type() if error.headers else None,
            redirect_count=int(error.geturl() != url),
            page_title=None,
            job_count=None,
            detail=f"HTTP {error.code}",
        )
    except ValueError:
        return _failure(url, ProbeOutcome.ACCESS_BLOCK, "redirect target is not public")
    except TimeoutError:
        return _failure(url, ProbeOutcome.TIMEOUT, "request timed out")
    except urllib.error.URLError as error:
        return _failure(url, ProbeOutcome.NETWORK_ERROR, _safe_network_reason(error.reason))

    if len(body) > MAX_RESPONSE_BYTES:
        return ProbeResult(
            requested_url=url,
            final_url=final_url,
            outcome=ProbeOutcome.RESPONSE_TOO_LARGE,
            status_code=status_code,
            content_type=content_type,
            redirect_count=int(final_url != url),
            page_title=None,
            job_count=None,
            detail=f"response exceeded {MAX_RESPONSE_BYTES} bytes",
        )

    return classify_probe_body(
        requested_url=url,
        final_url=final_url,
        status_code=status_code,
        content_type=content_type,
        body=body,
        expect_json_jobs=expect_json_jobs,
    )


def classify_probe_body(
    *,
    requested_url: str,
    final_url: str,
    status_code: int,
    content_type: str,
    body: bytes,
    expect_json_jobs: bool,
) -> ProbeResult:
    """Classify a bounded response body for tests and live probes."""
    text = body[:200_000].decode("utf-8", errors="replace")
    lowered = text.lower()
    page_title = extract_html_title(text)

    if expect_json_jobs:
        try:
            payload: Any = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if is_access_block_html(text, page_title):
                return _classified(
                    requested_url,
                    final_url,
                    status_code,
                    content_type,
                    ProbeOutcome.ACCESS_BLOCK,
                    "access-control or login page detected",
                )
            return _classified(
                requested_url,
                final_url,
                status_code,
                content_type,
                ProbeOutcome.INVALID_CONTENT,
                "expected JSON job data",
            )
        job_count = _job_count(payload)
        if job_count is None:
            return _classified(
                requested_url,
                final_url,
                status_code,
                content_type,
                ProbeOutcome.INVALID_CONTENT,
                "JSON payload does not expose a recognized jobs collection",
            )
        return ProbeResult(
            requested_url=requested_url,
            final_url=final_url,
            outcome=ProbeOutcome.SUCCESS,
            status_code=status_code,
            content_type=content_type,
            redirect_count=int(final_url != requested_url),
            page_title=None,
            job_count=job_count,
            detail="recognized public JSON jobs collection",
        )

    if "html" not in content_type and "<html" not in lowered:
        return _classified(
            requested_url,
            final_url,
            status_code,
            content_type,
            ProbeOutcome.INVALID_CONTENT,
            "expected a public HTML careers page",
        )
    if is_access_block_html(text, page_title):
        return _classified(
            requested_url,
            final_url,
            status_code,
            content_type,
            ProbeOutcome.ACCESS_BLOCK,
            "access-control or login page detected",
        )
    return ProbeResult(
        requested_url=requested_url,
        final_url=final_url,
        outcome=ProbeOutcome.SUCCESS,
        status_code=status_code,
        content_type=content_type,
        redirect_count=int(final_url != requested_url),
        page_title=page_title,
        job_count=None,
        detail="public HTML page retrieved",
    )


def _job_count(payload: object) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("jobs", "jobPostings", "postings"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    return None


def _classified(
    requested_url: str,
    final_url: str,
    status_code: int,
    content_type: str,
    outcome: ProbeOutcome,
    detail: str,
) -> ProbeResult:
    return ProbeResult(
        requested_url=requested_url,
        final_url=final_url,
        outcome=outcome,
        status_code=status_code,
        content_type=content_type,
        redirect_count=int(final_url != requested_url),
        page_title=None,
        job_count=None,
        detail=detail,
    )


def _failure(url: str, outcome: ProbeOutcome, detail: str) -> ProbeResult:
    return ProbeResult(
        requested_url=url,
        final_url=None,
        outcome=outcome,
        status_code=None,
        content_type=None,
        redirect_count=0,
        page_title=None,
        job_count=None,
        detail=detail,
    )


def _safe_network_reason(reason: object) -> str:
    text = str(reason).replace("\r", " ").replace("\n", " ")
    return f"network error: {text[:160]}"
