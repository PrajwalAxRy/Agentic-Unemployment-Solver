"""Measure what adopting shared normalization changes (to_change.md 1.2 / 6.3 / 9.4).

Run from the repository root:

    python docs/rewrite/check_normalization_impact.py

Compares the adapter-local helpers that Phase 1 deletes against the shared
``normalization/jobs.py`` functions that replace them, and -- more importantly -- checks
whether the *location filter decisions* change, not just the normalized strings. 9.4 says
to expect location output to shift; this shows the shift does not reach the verdicts.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from job_finder.core.search_profile import load_search_profile  # noqa: E402
from job_finder.filters.locations import filter_location  # noqa: E402
from job_finder.normalization.jobs import (  # noqa: E402
    normalize_location_values,
    normalize_title,
)

TITLES = (
    "Senior ML Engineer, Ads",
    "Staff Engineer (AI/ML)",
    "ML Engineer II",
    "Software Dev Engineer II, AWS Healthcare AI",
    "Data Scientist, Search & Discovery",
    "Sr. Applied Scientist - Prime Video",
    "C++ Developer",
    "Engineer III (Backend)",
)

LOCATIONS = (
    "Bengaluru, Karnataka, India",
    "Remote - India",
    "Hyderabad, Telangana, India | Pune, Maharashtra, India",
    "Bangalore or Hyderabad",
    "Gurugram/Noida",
    "Remote (APAC)",
    "Remote - United States",
    "San Francisco, CA",
    "London, UK",
    "Mumbai, Maharashtra, India",
    "Remote",
    "Chennai, Tamil Nadu, India",
    "Seattle, WA, USA",
    "Singapore",
    "Noida, Uttar Pradesh, India",
    "Remote, India",
)


def adapter_local_text(value: str) -> str:
    """The implementation 22 of 35 adapters used. Note: no punctuation stripping."""
    return re.sub(r"\s+", " ", value).strip().casefold()


def adapter_local_locations(value: str) -> tuple[str, ...]:
    """The most common of the ten local location variants (11 of 30 adapters)."""
    pieces = (adapter_local_text(part) for part in re.split(r"[,|;/]", value))
    return tuple(dict.fromkeys(piece for piece in pieces if piece))


def main() -> int:
    profile = load_search_profile(Path("config/search_profile.toml"))

    print("TITLE normalization (adapter-local vs shared)")
    for title in TITLES:
        local, shared = adapter_local_text(title), normalize_title(title)
        flag = "DIFF" if local != shared else " ok "
        print(f"  {flag}  {title!r}")
        if local != shared:
            print(f"          local  = {local!r}")
            print(f"          shared = {shared!r}")

    print("\nLOCATION filter decisions (the part that actually matters)")
    changed = 0
    for location in LOCATIONS:
        common = {
            "source_metadata": {},
            "source_type": "check",
            "policy": profile.location,
        }
        local_result = filter_location(
            location, normalized_locations=adapter_local_locations(location), **common
        )
        shared_result = filter_location(
            location,
            normalized_locations=normalize_location_values(location, policy=profile.location),
            **common,
        )
        same = local_result.decision is shared_result.decision
        changed += not same
        verdict = "same" if same else "*** CHANGED ***"
        print(
            f"  {location[:50]:52} "
            f"{local_result.decision.value:>7} -> {shared_result.decision.value:<7} {verdict}"
        )

    print(f"\ndecision changes: {changed}/{len(LOCATIONS)}")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
