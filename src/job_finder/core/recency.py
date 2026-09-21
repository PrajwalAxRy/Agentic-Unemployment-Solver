"""Rolling recency decisions and publication-date coverage measurements."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from job_finder.core.job_contracts import DateBasis
from job_finder.core.search_profile import DateUncertaintyMode


class DateEvidenceStatus(StrEnum):
    """Quality category for one listing's source date evidence."""

    RELIABLE = "reliable"
    UNCERTAIN = "uncertain"
    INVALID = "invalid"
    MISSING = "missing"


class RecencyDecision(StrEnum):
    """Rolling-window decision without hiding uncertain evidence."""

    INSIDE_WINDOW = "inside_window"
    OUTSIDE_WINDOW = "outside_window"
    UNCERTAIN = "uncertain"
    INVALID = "invalid"


class SourceAssessment(StrEnum):
    """Whether listing dates could be assessed for an enabled company."""

    OBSERVED = "observed"
    NO_LISTINGS = "no_listings"
    UNASSESSED = "unassessed"


class CompanyDateCoverageClass(StrEnum):
    """Required H5 company-level date-coverage categories."""

    ALL_RELIABLE = "all_reliable"
    MIXED = "mixed"
    NO_RELIABLE = "no_reliable"
    NO_LISTINGS = "no_listings"
    UNASSESSED = "unassessed"


@dataclass(frozen=True, slots=True)
class RecencyAssessment:
    """Explainable result of applying the rolling-window rule."""

    decision: RecencyDecision
    evidence_status: DateEvidenceStatus
    date_basis: DateBasis
    boundary: datetime
    measurement_pool: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ListingDateObservation:
    """Date evidence retained for one listing in the H5 measurement report."""

    company_id: str
    adapter_type: str
    evidence_status: DateEvidenceStatus
    date_basis: DateBasis
    raw_date_text: str | None
    job_url: str
    first_seen_at: datetime | None
    decision: RecencyDecision = RecencyDecision.UNCERTAIN
    reason: str = ""
    normalized_date: str | None = None

    def __post_init__(self) -> None:
        if not self.company_id.strip():
            raise ValueError("date observation company_id must be non-empty")
        if not self.adapter_type.strip():
            raise ValueError("date observation adapter_type must be non-empty")
        if not self.job_url.strip():
            raise ValueError("date observation job_url must be non-empty")
        if self.first_seen_at is not None and self.first_seen_at.tzinfo is None:
            raise ValueError("date observation first_seen_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CompanyDateCoverageInput:
    """Complete date-assessment input for one enabled company."""

    company_id: str
    company_name: str
    adapter_type: str
    assessment: SourceAssessment
    observations: tuple[ListingDateObservation, ...]

    def __post_init__(self) -> None:
        if not self.company_id.strip() or not self.company_name.strip():
            raise ValueError("company date coverage identity must be non-empty")
        if not self.adapter_type.strip():
            raise ValueError("company date coverage adapter_type must be non-empty")
        if self.assessment is SourceAssessment.OBSERVED and not self.observations:
            raise ValueError("observed company date coverage requires listings")
        if self.assessment is not SourceAssessment.OBSERVED and self.observations:
            raise ValueError("no-listing or unassessed company cannot contain observations")
        if any(item.company_id != self.company_id for item in self.observations):
            raise ValueError("date observation company_id does not match its company")
        if any(item.adapter_type != self.adapter_type for item in self.observations):
            raise ValueError("date observation adapter_type does not match its company")


@dataclass(frozen=True, slots=True)
class EvidenceCounts:
    """Listing counts for the four required date-evidence states."""

    reliable: int = 0
    uncertain: int = 0
    invalid: int = 0
    missing: int = 0

    @property
    def total(self) -> int:
        return self.reliable + self.uncertain + self.invalid + self.missing

    def percentages(self) -> Mapping[str, float]:
        """Return percentages using zero for an empty denominator."""
        if self.total == 0:
            return {name: 0.0 for name in ("reliable", "uncertain", "invalid", "missing")}
        return {
            "reliable": self.reliable / self.total * 100,
            "uncertain": self.uncertain / self.total * 100,
            "invalid": self.invalid / self.total * 100,
            "missing": self.missing / self.total * 100,
        }


@dataclass(frozen=True, slots=True)
class DecisionCounts:
    """Listing counts for rolling-window and measurement-pool decisions."""

    inside_window: int = 0
    outside_window: int = 0
    uncertain: int = 0
    invalid: int = 0

    @property
    def total(self) -> int:
        return self.inside_window + self.outside_window + self.uncertain + self.invalid


@dataclass(frozen=True, slots=True)
class CompanyDateCoverage:
    """Computed date-coverage result for one enabled company."""

    company_id: str
    company_name: str
    adapter_type: str
    coverage_class: CompanyDateCoverageClass
    listing_counts: EvidenceCounts
    decision_counts: DecisionCounts
    first_seen_available_count: int


@dataclass(frozen=True, slots=True)
class AdapterDateCoverage:
    """Required company and listing breakdown for one adapter family."""

    adapter_type: str
    company_count: int
    company_class_counts: Mapping[CompanyDateCoverageClass, int]
    listing_counts: EvidenceCounts
    decision_counts: DecisionCounts
    first_seen_available_count: int


@dataclass(frozen=True, slots=True)
class DateCoverageReport:
    """Full-registry H5 measurement contract."""

    enabled_company_count: int
    companies: tuple[CompanyDateCoverage, ...]
    company_class_counts: Mapping[CompanyDateCoverageClass, int]
    company_class_percentages: Mapping[CompanyDateCoverageClass, float]
    listing_counts: EvidenceCounts
    listing_percentages: Mapping[str, float]
    decision_counts: DecisionCounts
    by_adapter: Mapping[str, AdapterDateCoverage]
    first_seen_available_count: int


def assess_recency(
    value: datetime | date | None,
    *,
    basis: DateBasis,
    scan_at: datetime,
    window_days: int,
    uncertainty_mode: DateUncertaintyMode,
    publication_date_verified: bool,
) -> RecencyAssessment:
    """Assess one date against an explicit rolling window.

    The approved hybrid policy keeps unverified source dates in the separate uncertain-date
    section.  It uses ``first_seen`` only for a forward-only age decision after persistence has
    established that timestamp; it never treats it as a publication date.
    """
    if scan_at.tzinfo is None:
        raise ValueError("scan_at must be timezone-aware")
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if uncertainty_mode not in {
        DateUncertaintyMode.MEASURE_THEN_DECIDE,
        DateUncertaintyMode.HYBRID,
    }:
        raise ValueError("unsupported date-uncertainty behavior for recency assessment")

    boundary = scan_at - timedelta(days=window_days)
    if value is None:
        return RecencyAssessment(
            decision=RecencyDecision.UNCERTAIN,
            evidence_status=DateEvidenceStatus.MISSING,
            date_basis=basis,
            boundary=boundary,
            measurement_pool=True,
            reason="source publication date is missing",
        )

    if basis is DateBasis.FIRST_SEEN and uncertainty_mode is DateUncertaintyMode.HYBRID:
        if not isinstance(value, datetime):
            return RecencyAssessment(
                decision=RecencyDecision.UNCERTAIN,
                evidence_status=DateEvidenceStatus.UNCERTAIN,
                date_basis=basis,
                boundary=boundary,
                measurement_pool=True,
                reason="first-seen evidence lacks a timestamp and remains uncertain",
            )
        if value.tzinfo is None:
            raise ValueError("first-seen datetime must be timezone-aware")
        if value > scan_at:
            return RecencyAssessment(
                decision=RecencyDecision.INVALID,
                evidence_status=DateEvidenceStatus.INVALID,
                date_basis=basis,
                boundary=boundary,
                measurement_pool=True,
                reason="first-seen datetime is after the scan time",
            )
        return RecencyAssessment(
            decision=(
                RecencyDecision.INSIDE_WINDOW
                if value >= boundary
                else RecencyDecision.OUTSIDE_WINDOW
            ),
            evidence_status=DateEvidenceStatus.UNCERTAIN,
            date_basis=basis,
            boundary=boundary,
            measurement_pool=True,
            reason="forward-only first-seen timestamp determines uncertain-section aging",
        )

    if basis is not DateBasis.PUBLISHED or not publication_date_verified:
        return RecencyAssessment(
            decision=RecencyDecision.UNCERTAIN,
            evidence_status=DateEvidenceStatus.UNCERTAIN,
            date_basis=basis,
            boundary=boundary,
            measurement_pool=True,
            reason="date is not verified first-publication evidence",
        )

    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("publication datetime must be timezone-aware")
        if value > scan_at:
            return RecencyAssessment(
                decision=RecencyDecision.INVALID,
                evidence_status=DateEvidenceStatus.INVALID,
                date_basis=basis,
                boundary=boundary,
                measurement_pool=True,
                reason="publication datetime is after the scan time",
            )
        inside_window = value >= boundary
        return RecencyAssessment(
            decision=(
                RecencyDecision.INSIDE_WINDOW if inside_window else RecencyDecision.OUTSIDE_WINDOW
            ),
            evidence_status=DateEvidenceStatus.RELIABLE,
            date_basis=basis,
            boundary=boundary,
            measurement_pool=False,
            reason=(
                "verified publication datetime is inside the rolling window"
                if inside_window
                else "verified publication datetime is outside the rolling window"
            ),
        )

    scan_date = scan_at.date()
    boundary_date = boundary.date()
    if value > scan_date:
        return RecencyAssessment(
            decision=RecencyDecision.INVALID,
            evidence_status=DateEvidenceStatus.INVALID,
            date_basis=basis,
            boundary=boundary,
            measurement_pool=True,
            reason="publication date is after the scan date",
        )
    if value == boundary_date:
        return RecencyAssessment(
            decision=RecencyDecision.UNCERTAIN,
            evidence_status=DateEvidenceStatus.UNCERTAIN,
            date_basis=basis,
            boundary=boundary,
            measurement_pool=True,
            reason="date-only value overlaps the exact rolling-window boundary",
        )
    inside_window = value > boundary_date
    return RecencyAssessment(
        decision=(
            RecencyDecision.INSIDE_WINDOW if inside_window else RecencyDecision.OUTSIDE_WINDOW
        ),
        evidence_status=DateEvidenceStatus.RELIABLE,
        date_basis=basis,
        boundary=boundary,
        measurement_pool=False,
        reason=(
            "complete publication date is inside the rolling window"
            if inside_window
            else "complete publication date is outside the rolling window"
        ),
    )


def assess_listing_recency(
    value: datetime | date | None,
    *,
    raw_date_text: str | None,
    basis: DateBasis,
    scan_at: datetime,
    window_days: int,
    uncertainty_mode: DateUncertaintyMode,
    publication_date_verified: bool,
) -> RecencyAssessment:
    """Assess a listing while distinguishing missing from unparseable raw date evidence."""
    base = assess_recency(
        value,
        basis=basis,
        scan_at=scan_at,
        window_days=window_days,
        uncertainty_mode=uncertainty_mode,
        publication_date_verified=publication_date_verified,
    )
    if value is not None or raw_date_text is None or not raw_date_text.strip():
        return base
    if basis is DateBasis.PUBLISHED and publication_date_verified:
        return RecencyAssessment(
            decision=RecencyDecision.INVALID,
            evidence_status=DateEvidenceStatus.INVALID,
            date_basis=basis,
            boundary=base.boundary,
            measurement_pool=True,
            reason="verified publication field contains an unparseable value",
        )
    return RecencyAssessment(
        decision=RecencyDecision.UNCERTAIN,
        evidence_status=DateEvidenceStatus.UNCERTAIN,
        date_basis=basis,
        boundary=base.boundary,
        measurement_pool=True,
        reason="unparsed non-publication date evidence remains uncertain",
    )


def build_date_coverage_report(
    company_inputs: Iterable[CompanyDateCoverageInput],
) -> DateCoverageReport:
    """Aggregate the exact company, listing, adapter, and first-seen metrics required at H5."""
    inputs = tuple(company_inputs)
    company_ids = [item.company_id for item in inputs]
    if len(company_ids) != len(set(company_ids)):
        raise ValueError("date coverage input contains duplicate company IDs")

    companies = tuple(_company_coverage(item) for item in inputs)
    class_counter = Counter(company.coverage_class for company in companies)
    class_counts = {item: class_counter[item] for item in CompanyDateCoverageClass}
    enabled_company_count = len(companies)
    class_percentages = {
        item: (class_counts[item] / enabled_company_count * 100 if enabled_company_count else 0.0)
        for item in CompanyDateCoverageClass
    }
    listing_counts = _sum_evidence_counts(company.listing_counts for company in companies)

    companies_by_adapter: dict[str, list[CompanyDateCoverage]] = defaultdict(list)
    for company in companies:
        companies_by_adapter[company.adapter_type].append(company)

    by_adapter: dict[str, AdapterDateCoverage] = {}
    for adapter_type, adapter_companies in sorted(companies_by_adapter.items()):
        adapter_class_counter = Counter(company.coverage_class for company in adapter_companies)
        by_adapter[adapter_type] = AdapterDateCoverage(
            adapter_type=adapter_type,
            company_count=len(adapter_companies),
            company_class_counts={
                item: adapter_class_counter[item] for item in CompanyDateCoverageClass
            },
            listing_counts=_sum_evidence_counts(
                company.listing_counts for company in adapter_companies
            ),
            decision_counts=_sum_decision_counts(
                company.decision_counts for company in adapter_companies
            ),
            first_seen_available_count=sum(
                company.first_seen_available_count for company in adapter_companies
            ),
        )

    return DateCoverageReport(
        enabled_company_count=enabled_company_count,
        companies=companies,
        company_class_counts=class_counts,
        company_class_percentages=class_percentages,
        listing_counts=listing_counts,
        listing_percentages=listing_counts.percentages(),
        decision_counts=_sum_decision_counts(company.decision_counts for company in companies),
        by_adapter=by_adapter,
        first_seen_available_count=sum(company.first_seen_available_count for company in companies),
    )


def _company_coverage(item: CompanyDateCoverageInput) -> CompanyDateCoverage:
    if item.assessment is SourceAssessment.NO_LISTINGS:
        coverage_class = CompanyDateCoverageClass.NO_LISTINGS
    elif item.assessment is SourceAssessment.UNASSESSED:
        coverage_class = CompanyDateCoverageClass.UNASSESSED
    else:
        statuses = Counter(observation.evidence_status for observation in item.observations)
        reliable = statuses[DateEvidenceStatus.RELIABLE]
        other = len(item.observations) - reliable
        if reliable and not other:
            coverage_class = CompanyDateCoverageClass.ALL_RELIABLE
        elif reliable:
            coverage_class = CompanyDateCoverageClass.MIXED
        else:
            coverage_class = CompanyDateCoverageClass.NO_RELIABLE

    listing_counts = _evidence_counts(item.observations)
    return CompanyDateCoverage(
        company_id=item.company_id,
        company_name=item.company_name,
        adapter_type=item.adapter_type,
        coverage_class=coverage_class,
        listing_counts=listing_counts,
        decision_counts=_decision_counts(item.observations),
        first_seen_available_count=sum(
            observation.first_seen_at is not None for observation in item.observations
        ),
    )


def _evidence_counts(observations: Iterable[ListingDateObservation]) -> EvidenceCounts:
    counter = Counter(observation.evidence_status for observation in observations)
    return EvidenceCounts(
        reliable=counter[DateEvidenceStatus.RELIABLE],
        uncertain=counter[DateEvidenceStatus.UNCERTAIN],
        invalid=counter[DateEvidenceStatus.INVALID],
        missing=counter[DateEvidenceStatus.MISSING],
    )


def _sum_evidence_counts(counts: Iterable[EvidenceCounts]) -> EvidenceCounts:
    items = tuple(counts)
    return EvidenceCounts(
        reliable=sum(item.reliable for item in items),
        uncertain=sum(item.uncertain for item in items),
        invalid=sum(item.invalid for item in items),
        missing=sum(item.missing for item in items),
    )


def _decision_counts(observations: Iterable[ListingDateObservation]) -> DecisionCounts:
    counter = Counter(observation.decision for observation in observations)
    return DecisionCounts(
        inside_window=counter[RecencyDecision.INSIDE_WINDOW],
        outside_window=counter[RecencyDecision.OUTSIDE_WINDOW],
        uncertain=counter[RecencyDecision.UNCERTAIN],
        invalid=counter[RecencyDecision.INVALID],
    )


def _sum_decision_counts(counts: Iterable[DecisionCounts]) -> DecisionCounts:
    items = tuple(counts)
    return DecisionCounts(
        inside_window=sum(item.inside_window for item in items),
        outside_window=sum(item.outside_window for item in items),
        uncertain=sum(item.uncertain for item in items),
        invalid=sum(item.invalid for item in items),
    )
