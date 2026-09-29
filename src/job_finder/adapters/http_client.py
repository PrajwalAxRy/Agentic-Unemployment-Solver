"""Bounded public HTTP client shared by runtime job-source adapters."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from job_finder.core.access_detection import is_access_block_html
from job_finder.core.public_urls import PublicUrlRedirectHandler, validate_public_http_url

USER_AGENT = "job-finder/0.1 (manual public job-posting discovery)"
DEFAULT_MAX_RESPONSE_BYTES = 20_000_000


class HttpFailureCategory(StrEnum):
    """Sanitized failure categories safe for adapter diagnostics."""

    ACCESS_BLOCK = "access_block"
    HTTP_ERROR = "http_error"
    INVALID_CONTENT_TYPE = "invalid_content_type"
    NETWORK_ERROR = "network_error"
    REDIRECT_LIMIT = "redirect_limit"
    RESPONSE_TOO_LARGE = "response_too_large"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class HttpPolicy:
    """Request bounds applied consistently to every adapter."""

    timeout_seconds: float = 15.0
    retry_count: int = 2
    backoff_seconds: float = 0.5
    max_backoff_seconds: float = 4.0
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_redirects: int = 5

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if self.backoff_seconds < 0 or self.max_backoff_seconds < 0:
            raise ValueError("backoff bounds cannot be negative")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Successful bounded response with redirect and media-type metadata."""

    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    redirect_count: int
    body: bytes


class HttpRequestError(RuntimeError):
    """Sanitized request failure without response bodies or credential-bearing URLs."""

    def __init__(
        self,
        category: HttpFailureCategory,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class HttpTransport(Protocol):
    """Injectable transport hook used by fixture-backed adapter tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse: ...

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse: ...


class BoundedHttpClient:
    """Public GET and JSON POST client with shared request safeguards."""

    def __init__(
        self,
        *,
        policy: HttpPolicy | None = None,
        transport: HttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = policy or HttpPolicy()
        self._transport = transport or UrllibTransport()
        self._sleep = sleep

    def get(
        self,
        url: str,
        *,
        accepted_content_types: Sequence[str],
        referer: str | None = None,
    ) -> HttpResponse:
        """Retrieve one public URL and validate its declared media type."""
        return self._request(
            "GET",
            url,
            accepted_content_types=accepted_content_types,
            body=None,
            referer=referer,
        )

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        accepted_content_types: Sequence[str],
        referer: str | None = None,
    ) -> HttpResponse:
        """Send one bounded JSON request to a public endpoint."""
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return self._request(
            "POST",
            url,
            accepted_content_types=accepted_content_types,
            body=body,
            referer=referer,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        accepted_content_types: Sequence[str],
        body: bytes | None,
        referer: str | None,
    ) -> HttpResponse:
        _validate_public_url(url)
        if referer is not None:
            _validate_public_url(referer)
        accepted = tuple(item.strip().lower() for item in accepted_content_types if item.strip())
        if not accepted:
            raise ValueError("accepted_content_types must contain at least one media type")

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": ", ".join(accepted),
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
        if referer is not None:
            headers["Referer"] = referer
        for attempt in range(self.policy.retry_count + 1):
            try:
                if method == "GET":
                    response = self._transport.get(
                        url,
                        headers=headers,
                        timeout_seconds=self.policy.timeout_seconds,
                        max_response_bytes=self.policy.max_response_bytes,
                        max_redirects=self.policy.max_redirects,
                    )
                else:
                    if body is None:
                        raise AssertionError("POST request requires a body")
                    response = self._transport.post(
                        url,
                        headers=headers,
                        body=body,
                        timeout_seconds=self.policy.timeout_seconds,
                        max_response_bytes=self.policy.max_response_bytes,
                        max_redirects=self.policy.max_redirects,
                    )
            except HttpRequestError as error:
                if not error.retryable or attempt == self.policy.retry_count:
                    raise
                self._sleep(self._retry_delay(attempt, error.retry_after_seconds))
                continue

            content_type = response.content_type.lower()
            if not any(_content_type_matches(content_type, item) for item in accepted):
                if content_type == "text/html" and is_access_block_html(
                    response.body[:200_000].decode("utf-8", errors="replace")
                ):
                    raise HttpRequestError(
                        HttpFailureCategory.ACCESS_BLOCK,
                        "access-control or login page detected",
                        status_code=response.status_code,
                    )
                raise HttpRequestError(
                    HttpFailureCategory.INVALID_CONTENT_TYPE,
                    f"unexpected content type: {content_type or 'missing'}",
                    status_code=response.status_code,
                )
            return response
        raise AssertionError("unreachable retry loop")

    def _retry_delay(self, attempt: int, retry_after_seconds: float | None) -> float:
        exponential = self.policy.backoff_seconds * (2**attempt)
        requested = retry_after_seconds if retry_after_seconds is not None else exponential
        return min(max(requested, 0.0), self.policy.max_backoff_seconds)


class UrllibTransport:
    """Standard-library transport used for public read-only adapter requests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        return self._request(
            url,
            method="GET",
            headers=headers,
            body=None,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            max_redirects=max_redirects,
        )

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        return self._request(
            url,
            method="POST",
            headers=headers,
            body=body,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            max_redirects=max_redirects,
        )

    def _request(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
        max_redirects: int,
    ) -> HttpResponse:
        redirect_handler = _TrackingRedirectHandler(max_redirects)
        opener = urllib.request.build_opener(redirect_handler)
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise HttpRequestError(
                        HttpFailureCategory.RESPONSE_TOO_LARGE,
                        f"response exceeded {max_response_bytes} bytes",
                        status_code=response.status,
                    )
                return HttpResponse(
                    requested_url=url,
                    final_url=response.geturl(),
                    status_code=response.status,
                    content_type=response.headers.get_content_type(),
                    redirect_count=redirect_handler.redirect_count,
                    body=body,
                )
        except HttpRequestError:
            raise
        except urllib.error.HTTPError as error:
            if error.code == 310:
                raise HttpRequestError(
                    HttpFailureCategory.REDIRECT_LIMIT,
                    f"redirect count exceeded {max_redirects}",
                    status_code=error.code,
                ) from error
            retry_after = _retry_after_seconds(
                error.headers.get("Retry-After") if error.headers else None
            )
            category = (
                HttpFailureCategory.ACCESS_BLOCK
                if error.code in {401, 403}
                else HttpFailureCategory.HTTP_ERROR
            )
            raise HttpRequestError(
                category,
                f"HTTP {error.code}",
                status_code=error.code,
                retryable=error.code == 429 or 500 <= error.code <= 599,
                retry_after_seconds=retry_after,
            ) from error
        except TimeoutError as error:
            raise HttpRequestError(
                HttpFailureCategory.TIMEOUT,
                "request timed out",
                retryable=True,
            ) from error
        except (http.client.RemoteDisconnected, ConnectionError) as error:
            raise HttpRequestError(
                HttpFailureCategory.NETWORK_ERROR,
                "network connection closed",
                retryable=True,
            ) from error
        except urllib.error.URLError as error:
            reason = str(error.reason).replace("\r", " ").replace("\n", " ")[:160]
            raise HttpRequestError(
                HttpFailureCategory.NETWORK_ERROR,
                f"network error: {reason}",
                retryable=True,
            ) from error


class _TrackingRedirectHandler(PublicUrlRedirectHandler):
    def __init__(self, max_redirects: int) -> None:
        super().__init__()
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise urllib.error.HTTPError(
                req.full_url,
                310,
                "too many redirects",
                headers,
                fp,
            )
        try:
            _validate_public_url(newurl)
        except ValueError as error:
            raise HttpRequestError(
                HttpFailureCategory.ACCESS_BLOCK,
                "redirect target is not a public HTTP URL",
                status_code=code,
            ) from error
        return super().redirect_request(  # type: ignore[no-untyped-call]
            req, fp, code, msg, headers, newurl
        )


def _validate_public_url(url: str) -> None:
    validate_public_http_url(url, "request URL")


def _content_type_matches(actual: str, accepted: str) -> bool:
    if accepted == "*/*":
        return True
    if accepted.endswith("/*"):
        return actual.startswith(accepted[:-1])
    return actual == accepted


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
