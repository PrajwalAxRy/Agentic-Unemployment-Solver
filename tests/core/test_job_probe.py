"""Per-job liveness probing (to_change.md 3.2, 10.F).

10.F reframes the close-threshold debate: the real question was never "3 or 5" but
"does the URL probe reliably fire, and does it classify correctly". At 5 absences the
probe was a nice-to-have; at 3 it is the entire safety margin.

Two of these rules cannot be inferred from a status code, and both come straight from 3.2:
many boards serve "no longer available" with a 200, and a closed posting frequently
redirects to the search page rather than 404ing.
"""

from __future__ import annotations

import pytest

from job_finder.core.job_probe import ProbeVerdict, probe_job_url
from job_finder.core.source_probe import ProbeOutcome, ProbeResult

JOB_URL = "https://jobs.example.com/careers/job/12345"


def _result(
    *,
    outcome: ProbeOutcome = ProbeOutcome.SUCCESS,
    status_code: int | None = 200,
    final_url: str | None = None,
    page_title: str | None = "Machine Learning Engineer - Example",
) -> ProbeResult:
    return ProbeResult(
        requested_url=JOB_URL,
        final_url=final_url if final_url is not None else JOB_URL,
        outcome=outcome,
        status_code=status_code,
        content_type="text/html",
        redirect_count=0,
        page_title=page_title,
        job_count=None,
        detail="",
    )


def _probe(result: ProbeResult, *, listed: bool = False):
    return probe_job_url(JOB_URL, listed=listed, probe=lambda *a, **k: result)


@pytest.mark.parametrize("status", [404, 410])
def test_gone_status_closes_the_job(status: int) -> None:
    verdict = _probe(_result(outcome=ProbeOutcome.HTTP_ERROR, status_code=status))

    assert verdict.verdict is ProbeVerdict.CLOSED
    assert verdict.reason_code == "http_gone"
    assert verdict.advances_state is True


@pytest.mark.parametrize(
    "title",
    [
        "This job is no longer available",
        "Position closed - Example Careers",
        "Job not found",
        "404 - Not Found",
        "This posting has been removed",
    ],
)
def test_tombstone_page_served_with_200_is_detected(title: str) -> None:
    """3.2: many boards serve 'no longer available' with a 200."""
    verdict = _probe(_result(page_title=title))

    assert verdict.verdict is ProbeVerdict.CLOSED
    assert verdict.reason_code == "closed_page_text"


def test_redirect_to_the_search_page_is_treated_as_closed() -> None:
    """3.2: a closed posting frequently redirects to search rather than 404ing."""
    verdict = _probe(_result(final_url="https://jobs.example.com/careers/search"))

    assert verdict.verdict is ProbeVerdict.CLOSED
    assert verdict.reason_code == "redirected_to_search"


def test_redirect_up_to_the_parent_listing_is_treated_as_closed() -> None:
    verdict = _probe(_result(final_url="https://jobs.example.com/careers/job"))

    assert verdict.verdict is ProbeVerdict.CLOSED


def test_slug_canonicalization_is_not_a_closure() -> None:
    """The false positive that would matter most.

    Boards routinely rewrite /job/12345 to /job/12345-ml-engineer. Reading that as a
    closure would close live jobs on every probe -- strictly worse than not probing.
    """
    verdict = _probe(
        _result(final_url="https://jobs.example.com/careers/job/12345/ml-engineer"),
        listed=True,
    )

    assert verdict.verdict is ProbeVerdict.LIVE


@pytest.mark.parametrize(
    "outcome",
    [
        ProbeOutcome.TIMEOUT,
        ProbeOutcome.NETWORK_ERROR,
        ProbeOutcome.RESPONSE_TOO_LARGE,
        ProbeOutcome.ACCESS_BLOCK,
    ],
)
def test_transport_failures_yield_no_information(outcome: ProbeOutcome) -> None:
    """A probe that could not reach the server is not evidence about the job."""
    verdict = _probe(_result(outcome=outcome, status_code=None))

    assert verdict.verdict is ProbeVerdict.NO_INFORMATION
    assert verdict.advances_state is False


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_throttling_and_server_errors_yield_no_information(status: int) -> None:
    """3.2 names these explicitly: they advance nothing.

    A 429 in particular is a statement about our request rate, not about the job.
    """
    verdict = _probe(_result(outcome=ProbeOutcome.HTTP_ERROR, status_code=status))

    assert verdict.verdict is ProbeVerdict.NO_INFORMATION
    assert verdict.advances_state is False


def test_live_url_absent_from_the_listing_is_live_but_missing() -> None:
    """The branch that keeps a 3-absence threshold safe.

    Search-index lag behind a live page is routine on Workday and Oracle (5.3).
    """
    verdict = _probe(_result(), listed=False)

    assert verdict.verdict is ProbeVerdict.LIVE_BUT_MISSING
    assert verdict.reason_code == "live_but_absent_from_listing"


def test_live_url_present_in_the_listing_is_simply_live() -> None:
    verdict = _probe(_result(), listed=True)

    assert verdict.verdict is ProbeVerdict.LIVE


def test_a_missing_page_title_does_not_imply_closure() -> None:
    """Absence of evidence is not evidence of closure."""
    verdict = _probe(_result(page_title=None), listed=True)

    assert verdict.verdict is ProbeVerdict.LIVE


def test_probe_reuses_the_hardened_source_probe_path() -> None:
    """Built on probe_public_url, so it inherits SSRF validation and the size cap.

    This is why core/source_probe.py was exempted from the decision-B relocation.
    """
    from job_finder.core import job_probe

    assert job_probe.probe_public_url.__module__ == "job_finder.core.source_probe"
