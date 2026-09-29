"""Fixture-backed tests for Google's public India careers search."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_finder.adapters.base import AdapterConfigurationError
from job_finder.adapters.errors import DetailIdentityMismatch
from job_finder.adapters.google_careers import (
    GOOGLE_CAREERS_ADAPTER_KEY,
    GOOGLE_CAREERS_URL,
    GoogleCareersAdapter,
)
from job_finder.adapters.http_client import BoundedHttpClient, HttpPolicy, HttpResponse
from job_finder.core.job_contracts import DateBasis
from job_finder.core.search_profile import load_search_profile
from job_finder.core.source_contracts import (
    AdapterOutcome,
    AdapterType,
    CompanySource,
    Confidence,
    DateStrategy,
    DetailStrategy,
    IdentityStrategy,
    SourceStatus,
)
from job_finder.normalization.jobs import normalize_job

FIXTURES = Path(__file__).parents[1] / "fixtures" / "google_careers"


class RouteTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> HttpResponse:
        self.calls.append(url)
        response = self.responses.pop(0)
        return replace(response, requested_url=url, final_url=url)


def source() -> CompanySource:
    return CompanySource(
        schema_version=1,
        company_id="google",
        company_name="Google",
        status=SourceStatus.REVIEWED,
        careers_url=GOOGLE_CAREERS_URL,
        adapter_type=AdapterType.CUSTOM,
        adapter_parameters={"adapter_key": GOOGLE_CAREERS_ADAPTER_KEY},
        identity_strategy=IdentityStrategy.EXTERNAL_ID,
        date_strategy=DateStrategy(
            None, DateBasis.UNKNOWN, False, "Google Careers exposes no publication date."
        ),
        detail_strategy=DetailStrategy.DETAIL_PAGE,
        enabled=False,
        confidence=Confidence.HIGH,
        evidence=(GOOGLE_CAREERS_URL,),
        low_confidence_approved=False,
        exception_reason=None,
        notes="",
    )


def fixture(name: str) -> HttpResponse:
    return HttpResponse("", "", 200, "text/html", 0, (FIXTURES / name).read_bytes())


def adapter_for(
    responses: list[HttpResponse], *, page_size: int = 1
) -> tuple[GoogleCareersAdapter, RouteTransport]:
    transport = RouteTransport(responses)
    client = BoundedHttpClient(policy=HttpPolicy(retry_count=0), transport=transport)
    return GoogleCareersAdapter(client, page_size=page_size), transport


def test_count_checked_pagination_maps_stable_google_job_identity() -> None:
    adapter, transport = adapter_for([fixture("page_1.html"), fixture("page_2.html")])

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.complete is True
    assert result.page_count == 2
    assert [job.external_job_id for job in result.jobs] == ["111", "222"]
    first = result.jobs[0]
    assert first.canonical_url == (
        "https://www.google.com/about/careers/applications/jobs/results/"
        "111-machine-learning-engineer"
    )
    assert first.location_original == ("Bengaluru, Karnataka, India | Hyderabad, Telangana, India")
    assert first.location_normalized == (
        "bengaluru",
        "karnataka",
        "india",
        "hyderabad",
        "telangana",
    )
    assert first.published_at is None
    assert first.date_basis is DateBasis.UNKNOWN
    assert first.description is None
    assert first.source_metadata == {
        "adapter_key": GOOGLE_CAREERS_ADAPTER_KEY,
        "product": "Google",
        "experience_level": "Early",
        "listing_minimum_qualifications": (
            "Minimum qualifications\nBachelor's degree or equivalent practical experience."
        ),
        "india_search_result": True,
    }
    assert result.jobs[1].source_metadata["product"] == "YouTube"
    assert transport.calls == [GOOGLE_CAREERS_URL, f"{GOOGLE_CAREERS_URL}&page=2"]


def test_detail_page_maps_all_substantive_sections_and_preserves_identity() -> None:
    adapter, _ = adapter_for([fixture("page_1.html"), fixture("page_2.html")])
    listed = adapter.list_jobs(source()).jobs[0]
    detail_adapter, transport = adapter_for([fixture("detail.html")])

    detailed = detail_adapter.get_job_detail(source(), listed)

    assert detailed.external_job_id == listed.external_job_id
    assert detailed.canonical_url == listed.canonical_url
    assert detailed.description == (
        "Minimum qualifications\n\n"
        "Bachelor's degree or equivalent practical experience.\n"
        "2 years of experience with machine learning.\n\n"
        "Preferred qualifications\n\n"
        "Experience deploying production models.\n\n"
        "About the job\n\n"
        "Build machine learning systems for users.\n\n"
        "Responsibilities\n\n"
        "Design and evaluate models.\n"
        "Collaborate with engineers."
    )
    assert detailed.description_hash is not None
    assert "INTERNAL_PAGE_STATE" not in detailed.description
    assert detailed.source_metadata["product"] == "Google"
    assert detailed.source_metadata["experience_level"] == "Early"
    assert transport.calls == [listed.canonical_url]


def test_india_search_preserves_cross_location_rows_for_downstream_filtering() -> None:
    page = (
        (FIXTURES / "page_1.html")
        .read_text(encoding="utf-8")
        .replace("Bengaluru, Karnataka, India", "Singapore")
        .replace("Hyderabad, Telangana, India", "Sydney NSW, Australia")
    )
    adapter, _ = adapter_for(
        [HttpResponse("", "", 200, "text/html", 0, page.encode()), fixture("page_2.html")]
    )

    result = adapter.list_jobs(source())

    assert result.outcome is AdapterOutcome.SUCCESS
    assert result.jobs[0].location_original == "Singapore | Sydney NSW, Australia"
    assert result.jobs[0].source_metadata["india_search_result"] is True


def test_malformed_duplicate_and_count_drift_fail_closed() -> None:
    malformed_html = (
        (FIXTURES / "page_1.html")
        .read_text(encoding="utf-8")
        .replace('data-id="111"', 'data-id="999"')
    )
    malformed, _ = adapter_for([HttpResponse("", "", 200, "text/html", 0, malformed_html.encode())])
    malformed_result = malformed.list_jobs(source())
    assert malformed_result.outcome is AdapterOutcome.FAILED
    assert malformed_result.diagnostics[-1].category == "malformed_job"

    duplicate, _ = adapter_for([fixture("page_1.html"), fixture("page_1.html")])
    duplicate_result = duplicate.list_jobs(source())
    assert duplicate_result.outcome is AdapterOutcome.SUSPICIOUS
    assert duplicate_result.diagnostics[-1].category == "duplicate_job_id"

    changed_html = (
        (FIXTURES / "page_2.html")
        .read_text(encoding="utf-8")
        .replace('<span class="SWhIm">2</span>', '<span class="SWhIm">3</span>')
    )
    drift, _ = adapter_for(
        [
            fixture("page_1.html"),
            HttpResponse("", "", 200, "text/html", 0, changed_html.encode()),
        ]
    )
    drift_result = drift.list_jobs(source())
    assert drift_result.outcome is AdapterOutcome.SUSPICIOUS
    assert drift_result.diagnostics[-1].category == "changing_total"


def test_invalid_source_configuration_is_rejected_before_network() -> None:
    adapter, transport = adapter_for([fixture("page_1.html")])
    with pytest.raises(AdapterConfigurationError, match="adapter_key=google_careers_india"):
        adapter.list_jobs(replace(source(), adapter_parameters={"adapter_key": "other"}))
    with pytest.raises(AdapterConfigurationError, match="requires careers_url"):
        adapter.list_jobs(replace(source(), careers_url="https://google.com/careers"))
    assert transport.calls == []


# ---------------------------------------------------------------------------
# Regression tests for the title-normalization identity bug (to_change.md 1.2, 1.3, 9.5)
# ---------------------------------------------------------------------------
#
# The pre-existing detail test fed get_job_detail a *raw* listing straight from
# list_jobs(). Production never does that: scan.py normalizes every listing through
# normalize_job() first, and normalize_job strips punctuation from the title. The adapter's
# identity guard then compared its own punctuation-preserving _normalize_text against the
# already-stripped title_normalized, so every title containing a comma, hyphen, slash or
# parenthesis failed -- which is most real AI/ML titles. It hit 78/78 Google rows.
#
# The old test passed only because its fixture title ("Machine Learning Engineer") happens
# to contain no punctuation at all, so both normalizers agreed. These tests exercise the
# real call path and parametrize over the exact cases reproduced in the 1.2 table.


_FIXED_IN_PHASE_1 = (
    "Fixed in Phase 1: the adapter-local _normalize_text copies were deleted and every "
    "adapter now imports normalization/jobs.py, so the punctuation-keeping vs "
    "punctuation-stripping mismatch that broke 78/78 Google rows cannot recur. These "
    "cases stay as regression cover."
)


def _fixture_html(name: str, *, title: str) -> HttpResponse:
    """Return a fixture with its job title replaced, to vary punctuation."""
    html = (FIXTURES / name).read_text(encoding="utf-8")
    replaced = html.replace("Machine Learning Engineer", title)
    assert replaced != html, f"fixture {name} did not contain the expected placeholder title"
    return HttpResponse("", "", 200, "text/html", 0, replaced.encode("utf-8"))


@pytest.mark.parametrize(
    "title",
    [
        pytest.param("Senior ML Engineer, Ads", id="comma"),
        pytest.param("Staff Engineer (AI/ML)", id="parentheses-and-slash"),
        pytest.param("ML Engineer II", id="no-punctuation-control"),
        pytest.param("Software Engineer III, Machine Learning - Search", id="comma-and-hyphen"),
    ],
)
def test_detail_identity_survives_normalization_for_punctuated_titles(title: str) -> None:
    """get_job_detail must accept a listing that has been through normalize_job().

    This is the call path scan.py actually uses. Before the fix, every id except
    ``no-punctuation-control`` raised on the title identity guard.
    """
    profile = load_search_profile(Path("config/search_profile.toml"))
    listing_adapter, _ = adapter_for(
        [_fixture_html("page_1.html", title=title), fixture("page_2.html")]
    )
    listed = listing_adapter.list_jobs(source()).jobs[0]

    # The transformation the old test skipped.
    normalized = normalize_job(listed, location_policy=profile.location)

    detail_adapter, transport = adapter_for([_fixture_html("detail.html", title=title)])
    detailed = detail_adapter.get_job_detail(source(), normalized)

    assert detailed.title_original == title
    assert detailed.external_job_id == normalized.external_job_id
    assert detailed.canonical_url == normalized.canonical_url
    assert detailed.description is not None
    assert transport.calls == [normalized.canonical_url]


def test_detail_title_mismatch_raises_identity_mismatch_not_bare_value_error() -> None:
    """A genuine mismatch must be diagnosable as such.

    Asserting on the specific type matters: the original bug was invisible because a
    title-guard failure and a 403 both surfaced as an unexplained ValueError. Asserting
    ValueError here would let the test pass for the wrong reason again (9.5).
    """
    profile = load_search_profile(Path("config/search_profile.toml"))
    listing_adapter, _ = adapter_for(
        [_fixture_html("page_1.html", title="ML Engineer II"), fixture("page_2.html")]
    )
    listed = listing_adapter.list_jobs(source()).jobs[0]
    normalized = normalize_job(listed, location_policy=profile.location)

    # Detail page genuinely advertises a different role.
    detail_adapter, _ = adapter_for([_fixture_html("detail.html", title="Product Manager II")])

    with pytest.raises(DetailIdentityMismatch, match="title does not match"):
        detail_adapter.get_job_detail(source(), normalized)


def test_adapter_defines_no_local_normalization_helpers() -> None:
    """The root cause is gone by construction: there is only one implementation.

    ``to_change.md`` 1.2 originally reproduced the bug as a table of titles where the
    shared normalizer and the adapter's local ``_normalize_text`` disagreed. Phase 1
    deleted every local copy, so the two can no longer diverge -- there is nothing left to
    compare. This asserts the stronger property instead: the module must not reintroduce a
    local copy. A repo-wide version of this guard lives in
    ``tests/test_normalization_single_source.py``.
    """
    source = (
        Path(__file__).parents[2] / "src" / "job_finder" / "adapters" / "google_careers.py"
    ).read_text(encoding="utf-8")
    assert "def _normalize_text" not in source
    assert "def _normalized_locations" not in source
    assert "from job_finder.normalization.jobs import" in source
