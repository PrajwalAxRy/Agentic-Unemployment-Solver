"""Per-job liveness probing for staleness detection.

``to_change.md`` 3.2 makes absence the signal and probing the confirmation. Under the
3-absence close rule the probe is not a nice-to-have: it is the entire safety margin.

    Failure mode: a board silently returns 50 of 200 jobs with no error. Job 150 reads as
    absent; three such days close a live posting. The probe is the only guard -- a live
    URL routes to live-but-missing instead of closing. (10.F)

Built on :func:`job_finder.core.source_probe.probe_public_url` rather than a fresh HTTP
path, so it inherits SSRF validation on every redirect target, the response-size cap, and
the sanitized errors that never carry credentials. That reuse is why ``source_probe`` was
deliberately exempted from the decision-B relocation to ``scripts/``.

Two detection rules come straight from 3.2 and neither is inferable from the status code:

* many boards serve "this job is no longer available" with a **200**
* a closed posting frequently **redirects to the search page** rather than 404ing
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from job_finder.core.source_probe import ProbeOutcome, ProbeResult, probe_public_url

_LOGGER = logging.getLogger(__name__)

# Phrases boards use on a tombstone page that still returns HTTP 200. Matched against the
# page title only -- the title is the one piece of page content source_probe already
# extracts, and matching the full body would be both unbounded and far easier to fool.
_CLOSED_TITLE_PATTERNS = (
    re.compile(r"no longer (?:available|accepting|open|active)", re.IGNORECASE),
    re.compile(r"(?:job|position|requisition|posting)\s+(?:closed|expired|filled)", re.IGNORECASE),
    re.compile(
        r"(?:this )?(?:job|position|posting)\s+(?:is |has )?(?:been )?removed", re.IGNORECASE
    ),
    re.compile(r"\b(?:page|job)\s+not\s+found\b", re.IGNORECASE),
    re.compile(r"\b404\b", re.IGNORECASE),
)

# Landing paths that mean "we sent you to the search page instead of the job".
_SEARCH_PATH_MARKERS = ("/search", "/jobs", "/careers", "/opportunities", "/listings")


class ProbeVerdict(StrEnum):
    """What one probe says about a job's liveness (``to_change.md`` 3.2)."""

    LIVE = "live"
    """The posting resolved and still looks like itself."""

    CLOSED = "closed"
    """Definitively gone: 404/410, a tombstone page, or a redirect to search.
    Closes the job immediately rather than waiting out the absence counter."""

    LIVE_BUT_MISSING = "live_but_missing"
    """The URL resolves but the job is absent from listings. Runs on its own 3-day
    clock rather than the plain-absence counter, because this is the shape a
    search-index lag takes (Workday and Oracle do this routinely)."""

    NO_INFORMATION = "no_information"
    """Timeout, 429, or 5xx. **Advances nothing.** A probe that could not reach the
    server is not evidence about the job, and treating it as such is how a bad
    afternoon on the network closes live postings."""


@dataclass(frozen=True, slots=True)
class JobProbeResult:
    """Sanitized, storable outcome of one job liveness probe."""

    verdict: ProbeVerdict
    reason_code: str
    status_code: int | None
    final_url: str | None
    detail: str

    @property
    def advances_state(self) -> bool:
        """Whether this probe may move the job's lifecycle state at all."""
        return self.verdict is not ProbeVerdict.NO_INFORMATION


def probe_job_url(
    url: str,
    *,
    listed: bool,
    timeout_seconds: float = 12.0,
    probe: object = None,
) -> JobProbeResult:
    """Probe one job URL and classify its liveness.

    ``listed`` is whether the job was seen in the company's listing on this run. It
    distinguishes the two live outcomes: a live URL that is *also* listed is simply
    ``LIVE``, while a live URL that is *absent* from the listing is the
    ``LIVE_BUT_MISSING`` case with its own slower clock.

    ``probe`` is injectable purely for testing; production uses ``probe_public_url``.
    """
    probe_callable = probe or probe_public_url
    result: ProbeResult = probe_callable(  # type: ignore[operator]
        url,
        expect_json_jobs=False,
        timeout_seconds=timeout_seconds,
    )

    verdict, reason_code = _classify(url, result, listed=listed)
    _LOGGER.debug(
        "job_probe url=%s verdict=%s reason=%s status=%s final=%s",
        url,
        verdict.value,
        reason_code,
        result.status_code,
        result.final_url,
    )
    return JobProbeResult(
        verdict=verdict,
        reason_code=reason_code,
        status_code=result.status_code,
        final_url=result.final_url,
        detail=result.detail,
    )


def _classify(url: str, result: ProbeResult, *, listed: bool) -> tuple[ProbeVerdict, str]:
    if result.outcome is ProbeOutcome.HTTP_ERROR and result.status_code in (404, 410):
        return ProbeVerdict.CLOSED, "http_gone"

    # Everything else that failed to produce a usable response tells us nothing. Note
    # this deliberately includes 429 and 5xx: they are statements about the server, not
    # about the job (3.2).
    if result.outcome is not ProbeOutcome.SUCCESS:
        return ProbeVerdict.NO_INFORMATION, f"probe_{result.outcome.value}"

    if _is_closed_title(result.page_title):
        return ProbeVerdict.CLOSED, "closed_page_text"

    if _redirected_to_search(url, result.final_url):
        return ProbeVerdict.CLOSED, "redirected_to_search"

    if listed:
        return ProbeVerdict.LIVE, "live_and_listed"
    return ProbeVerdict.LIVE_BUT_MISSING, "live_but_absent_from_listing"


def _is_closed_title(page_title: str | None) -> bool:
    """Detect a tombstone page served with HTTP 200 (3.2)."""
    if not page_title:
        return False
    return any(pattern.search(page_title) for pattern in _CLOSED_TITLE_PATTERNS)


def _redirected_to_search(requested_url: str, final_url: str | None) -> bool:
    """Detect a redirect away from the job onto a listing or search page (3.2).

    Only a redirect that *leaves* the original path counts. A board that canonicalizes
    ``/jobs/123`` to ``/jobs/123-some-slug`` has not closed anything, and treating that as
    closed would be far worse than missing a genuine closure.
    """
    if not final_url or final_url == requested_url:
        return False

    requested_path = urlsplit(requested_url).path.rstrip("/")
    final_parts = urlsplit(final_url)
    final_path = final_parts.path.rstrip("/")

    if final_path == requested_path:
        return False
    # Still inside the original job path (slug canonicalization) -- not a closure.
    if requested_path and final_path.startswith(f"{requested_path}/"):
        return False
    if requested_path.startswith(f"{final_path}/") and len(final_path) > 1:
        # Redirected *up* to a parent path, e.g. /jobs/123 -> /jobs. That is the search
        # page, which is exactly the signal 3.2 describes.
        return True

    normalized = final_path.lower()
    if normalized in ("", "/"):
        return True
    return any(
        normalized == marker or normalized.endswith(marker) for marker in _SEARCH_PATH_MARKERS
    )
