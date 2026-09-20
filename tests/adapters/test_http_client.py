"""Tests for the bounded adapter HTTP client."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from job_finder.adapters.http_client import (
    BoundedHttpClient,
    HttpFailureCategory,
    HttpPolicy,
    HttpRequestError,
    HttpResponse,
)


class FakeTransport:
    def __init__(self, outcomes: list[HttpResponse | HttpRequestError]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, Mapping[str, str], float, int, int]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        self.calls.append((url, headers, timeout_seconds, max_response_bytes, max_redirects))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, HttpRequestError):
            raise outcome
        return outcome


def response(*, content_type: str = "application/json") -> HttpResponse:
    return HttpResponse(
        requested_url="https://jobs.example.com/api",
        final_url="https://jobs.example.com/api",
        status_code=200,
        content_type=content_type,
        redirect_count=0,
        body=b'{"jobs": []}',
    )


def test_success_applies_truthful_identity_and_all_bounds() -> None:
    transport = FakeTransport([response()])
    policy = HttpPolicy(
        timeout_seconds=3,
        retry_count=0,
        max_response_bytes=1234,
        max_redirects=2,
    )

    result = BoundedHttpClient(policy=policy, transport=transport).get(
        "https://jobs.example.com/api",
        accepted_content_types=("application/json",),
    )

    assert result.status_code == 200
    url, headers, timeout, max_bytes, max_redirects = transport.calls[0]
    assert url == "https://jobs.example.com/api"
    assert headers["User-Agent"].startswith("job-finder/")
    assert headers["Accept"] == "application/json"
    assert (timeout, max_bytes, max_redirects) == (3, 1234, 2)


def test_retryable_failure_uses_bounded_backoff_then_succeeds() -> None:
    transport = FakeTransport(
        [
            HttpRequestError(
                HttpFailureCategory.HTTP_ERROR,
                "HTTP 429",
                status_code=429,
                retryable=True,
                retry_after_seconds=30,
            ),
            response(),
        ]
    )
    delays: list[float] = []
    client = BoundedHttpClient(
        policy=HttpPolicy(retry_count=1, backoff_seconds=0.25, max_backoff_seconds=2),
        transport=transport,
        sleep=delays.append,
    )

    result = client.get(
        "https://jobs.example.com/api",
        accepted_content_types=("application/json",),
    )

    assert result.status_code == 200
    assert len(transport.calls) == 2
    assert delays == [2]


def test_non_retryable_failure_is_not_repeated() -> None:
    error = HttpRequestError(
        HttpFailureCategory.HTTP_ERROR,
        "HTTP 404",
        status_code=404,
    )
    transport = FakeTransport([error])

    with pytest.raises(HttpRequestError) as raised:
        BoundedHttpClient(transport=transport).get(
            "https://jobs.example.com/api",
            accepted_content_types=("application/json",),
        )

    assert raised.value.category is HttpFailureCategory.HTTP_ERROR
    assert len(transport.calls) == 1


def test_unexpected_content_type_is_rejected_without_body_logging() -> None:
    transport = FakeTransport([response(content_type="text/html")])

    with pytest.raises(HttpRequestError, match="unexpected content type") as raised:
        BoundedHttpClient(transport=transport).get(
            "https://jobs.example.com/api",
            accepted_content_types=("application/json",),
        )

    assert raised.value.category is HttpFailureCategory.INVALID_CONTENT_TYPE
    assert "jobs" not in str(raised.value)


def test_visible_access_block_html_is_classified_without_logging_its_body() -> None:
    body = Path("tests/fixtures/ashby/access_block.html").read_bytes()
    blocked_response = response(content_type="text/html")
    blocked_response = HttpResponse(
        requested_url=blocked_response.requested_url,
        final_url=blocked_response.final_url,
        status_code=blocked_response.status_code,
        content_type=blocked_response.content_type,
        redirect_count=blocked_response.redirect_count,
        body=body,
    )

    with pytest.raises(HttpRequestError) as raised:
        BoundedHttpClient(transport=FakeTransport([blocked_response])).get(
            "https://jobs.example.com/api",
            accepted_content_types=("application/json",),
        )

    assert raised.value.category is HttpFailureCategory.ACCESS_BLOCK
    assert "Verify you are human" not in str(raised.value)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/jobs.json",
        "https://user:password@jobs.example.com/api",
        "jobs.example.com/api",
    ],
)
def test_non_public_or_credential_bearing_urls_are_rejected(url: str) -> None:
    transport = FakeTransport([response()])

    with pytest.raises(ValueError, match="request URL"):
        BoundedHttpClient(transport=transport).get(
            url,
            accepted_content_types=("application/json",),
        )

    assert not transport.calls
