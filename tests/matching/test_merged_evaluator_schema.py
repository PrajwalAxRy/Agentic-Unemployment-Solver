"""Tests for the merged response schema itself (not the parser).

This pins a property the parser cannot see, because ``parse_merged_response`` accepts any
:class:`DetectedLevel` regardless of what the JSON schema permits the model to generate --
the constraint that matters lives in the schema sent to the model under strict mode.

Note: ``maxLength`` bounds on the free-text fields were deliberately evaluated and
deferred (see CLAUDE.md "Settled decisions" / "Known-latent issues") based on 259 real
responses showing no violations against a 500-char cap. Do not add tests asserting
``maxLength`` presence without new measured evidence backing a specific cap.
"""

from __future__ import annotations

from job_finder.matching.merged_evaluator import MERGED_RESPONSE_SCHEMA
from job_finder.matching.seniority import DetectedLevel


def test_detected_level_enum_covers_every_supported_level() -> None:
    """A strict-schema call must be able to return every level the parser accepts.

    Previously the schema hand-copied 8 of DetectedLevel's 12 values, omitting
    staff/manager/director/executive -- the model could never return those levels even
    though seniority.py's DetectedLevel (and the merged parser) both support them.
    """
    schema_levels = set(MERGED_RESPONSE_SCHEMA["properties"]["detected_level"]["enum"])
    all_levels = {level.value for level in DetectedLevel}

    assert schema_levels == all_levels
