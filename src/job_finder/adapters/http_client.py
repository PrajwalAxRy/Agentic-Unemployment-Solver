"""Bounded public HTTP client shared by runtime job-source adapters."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

USER_AGENT = "job-finder/0.1 (manual public job-posting discovery)"


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
    max_response_bytes: int = 5_000_000
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


class BoundedHttpClient:
    """GET-only client with bounded retries, response size, redirects, and diagnostics."""

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
    ) -> HttpResponse:
        """Retrieve one public URL and validate its declared media type."""
        _validate_public_url(url)
        accepted = tuple(item.strip().lower() for item in accepted_content_types if item.strip())
        if not accepted:
            raise ValueError("accepted_content_types must contain at least one media type")

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": ", ".join(accepted),
        }
        for attempt in range(self.policy.retry_count + 1):
            try:
                response = self._transport.get(
                    url,
                    headers=headers,
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
        redirect_handler = _TrackingRedirectHandler(max_redirects)
        opener = urllib.request.build_opener(redirect_handler)
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
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
        except urllib.error.URLError as error:
            reason = str(error.reason).replace("\r", " ").replace("\n", " ")[:160]
            raise HttpRequestError(
                HttpFailureCategory.NETWORK_ERROR,
                f"network error: {reason}",
                retryable=True,
            ) from error


class _TrackingRedirectHandler(urllib.request.HTTPRedirectHandler):
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
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("request URL must be absolute HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("request URL must not contain credentials")


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
