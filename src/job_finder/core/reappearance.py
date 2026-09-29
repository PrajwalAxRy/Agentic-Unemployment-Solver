"""Reappearance monitoring (to_change.md 5.3).

The framing that matters here, and the reason this is a rate monitor rather than an alert
on each event:

    Reappearance is **not** inherently an error.

Legitimate causes are routine -- recruiter unpublish and republish, board freshness
rotation, a search index lagging behind a live page (Workday and Oracle both do this), and
a job ageing out of the default view. The probe already handles these: a live URL routes
to live-but-missing rather than closing.

So alerting on reappearance itself would mean investigating normal churn every day, which
in practice means investigating nothing. The trigger is the **rate per source**: a couple
a week across 44k listings is normal; dozens in a day from one company is a bug.

One shape is genuinely anomalous regardless of rate, and it gets its own flag: absent from
the listing **and** the URL 404s **and** the job later returns. That sequence should not
happen -- something claimed the job was definitively gone and was wrong.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field

_LOGGER = logging.getLogger(__name__)

DEFAULT_DAILY_THRESHOLD = 10
"""Reappearances from one source in one day before the source is flagged.

Calibrated from 5.3's own numbers: 'a couple a week across 44k listings is normal; dozens
in a day from one company is a bug'. Deliberately set between those, and it is a
code-review trigger rather than a pager.
"""


@dataclass(frozen=True, slots=True)
class ReappearanceEvent:
    """One job that returned to a listing after being absent."""

    job_key: str
    company_id: str
    canonical_url: str
    absences_before_return: int
    was_probed_gone: bool
    """True if a probe had reported the URL definitively gone (404/410 or tombstone).

    This is the anomalous shape: something concluded the job was gone and was wrong.
    """


@dataclass(frozen=True, slots=True)
class SourceReappearanceSummary:
    """Per-source reappearance counts for one run."""

    company_id: str
    reappearance_count: int
    probed_gone_count: int
    exceeded_threshold: bool

    @property
    def needs_review(self) -> bool:
        """Whether this source warrants a code review (5.3's actual trigger)."""
        return self.exceeded_threshold or self.probed_gone_count > 0


@dataclass(slots=True)
class ReappearanceMonitor:
    """Collects reappearance events and flags anomalous sources."""

    daily_threshold: int = DEFAULT_DAILY_THRESHOLD
    events: list[ReappearanceEvent] = field(default_factory=list)
    _per_source: Counter[str] = field(default_factory=Counter)
    _probed_gone: Counter[str] = field(default_factory=Counter)

    def record(self, event: ReappearanceEvent) -> None:
        """Record one reappearance. Routine by default; only the rate is interesting."""
        self.events.append(event)
        self._per_source[event.company_id] += 1
        if event.was_probed_gone:
            self._probed_gone[event.company_id] += 1
            # Logged individually because this specific sequence should not occur: the
            # probe said definitively gone, and it was wrong.
            _LOGGER.warning(
                "reappearance_after_probed_gone job=%s company=%s url=%s absences=%d",
                event.job_key,
                event.company_id,
                event.canonical_url,
                event.absences_before_return,
            )

    def summaries(self) -> tuple[SourceReappearanceSummary, ...]:
        return tuple(
            SourceReappearanceSummary(
                company_id=company_id,
                reappearance_count=count,
                probed_gone_count=self._probed_gone.get(company_id, 0),
                exceeded_threshold=count >= self.daily_threshold,
            )
            for company_id, count in sorted(self._per_source.items())
        )

    def sources_needing_review(self) -> tuple[SourceReappearanceSummary, ...]:
        return tuple(item for item in self.summaries() if item.needs_review)

    def as_json(self) -> dict[str, object]:
        flagged = self.sources_needing_review()
        for summary in flagged:
            _LOGGER.warning(
                "reappearance_anomaly company=%s count=%d probed_gone=%d threshold=%d",
                summary.company_id,
                summary.reappearance_count,
                summary.probed_gone_count,
                self.daily_threshold,
            )
        return {
            "schema_version": 1,
            "daily_threshold": self.daily_threshold,
            "total_reappearances": len(self.events),
            "sources": [asdict(item) for item in self.summaries()],
            "sources_needing_review": [item.company_id for item in flagged],
        }
