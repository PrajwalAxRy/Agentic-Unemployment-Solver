"""Merged relevance + seniority + location judgment (to_change.md 2.5, 2.6).

The point of the merge is one call per job. The risk is that merging the call also merges
the diagnostics -- if a single verdict came back with a single justification, a relevance
misfire and a seniority misfire would look identical. These tests pin the properties that
keep the three judgments separable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_finder.matching.merged_prompt import (
    LocationFit,
    MergedResponseError,
    RelevanceTier,
    load_merged_prompt,
    parse_merged_response,
)
from job_finder.matching.seniority import DetectedLevel

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "config" / "merged_prompt.toml"

DESCRIPTION = (
    "Design and build large-scale machine learning systems for Ads ranking. You will "
    "train and evaluate deep models and own model-serving infrastructure. Requires 3+ "
    "years of relevant experience. This role may be performed remotely from India."
)


def _response(**overrides: object) -> str:
    payload: dict[str, object] = {
        "work_summary": "Builds and trains ranking models for Ads.",
        "relevance": "core_ai",
        "relevance_evidence": "train and evaluate deep models",
        "relevance_reason": "The engineer trains and evaluates models directly.",
        "seniority_match": True,
        "detected_level": "mid",
        "required_experience": "3+ years",
        "seniority_evidence": "Requires 3+ years of relevant experience",
        "seniority_reason": "The stated minimum is below five years.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_shipped_prompt_loads_and_validates() -> None:
    prompt = load_merged_prompt(PROMPT)

    assert prompt.schema_version == 2
    assert prompt.prompt_version
    # The policy's load-bearing rules must be encoded explicitly, or the merge silently
    # drops the guidance the relevance gate exists to apply (screening policy v1.2).
    # Whitespace is collapsed first because the prompt is hard-wrapped.
    system = " ".join(prompt.system_prompt.split()).casefold()
    assert "ai only in the company description" in system
    assert "using ai tools at work" in system
    assert "the title alone is enough" in system
    assert "testing, validating, supporting or securing ai systems" in system
    assert "a stated number always beats the title" in system


def test_a_schema_1_prompt_is_refused(tmp_path: Path) -> None:
    """1.x answers in a different vocabulary; mapping it silently would mislabel jobs."""
    legacy = tmp_path / "legacy.toml"
    legacy.write_text(
        PROMPT.read_text(encoding="utf-8").replace("schema_version = 2", "schema_version = 1"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema_version"):
        load_merged_prompt(legacy)


def test_location_section_is_omitted_when_location_is_already_resolved() -> None:
    """2.5: cheap deterministic decisions still happen before the model."""
    prompt = load_merged_prompt(PROMPT)

    rendered = prompt.render(
        title="ML Engineer",
        description=DESCRIPTION,
        target_description="fewer than five years",
    )

    assert "Location as stated by the source" not in rendered
    assert "{location_section}" not in rendered


def test_location_section_is_included_when_requested() -> None:
    prompt = load_merged_prompt(PROMPT)

    rendered = prompt.render(
        title="ML Engineer",
        description=DESCRIPTION,
        target_description="fewer than five years",
        location_original="Remote",
    )

    assert "Location as stated by the source" in rendered
    assert "Remote" in rendered


def test_each_judgment_keeps_its_own_verdict_evidence_and_reason() -> None:
    """The property that makes a failing sub-judgment diagnosable (2.5)."""
    judgment = parse_merged_response(_response(), description=DESCRIPTION, location_requested=False)

    assert judgment.work_summary == "Builds and trains ranking models for Ads."
    assert judgment.relevance is RelevanceTier.CORE_AI
    assert judgment.relevance_evidence == "train and evaluate deep models"
    assert judgment.seniority_match is True
    assert judgment.detected_level is DetectedLevel.MID
    assert judgment.required_experience == "3+ years"
    assert judgment.seniority_evidence == "Requires 3+ years of relevant experience"
    # Distinct evidence per judgment -- not one quote reused for both.
    assert judgment.relevance_evidence != judgment.seniority_evidence


def test_fabricated_evidence_is_rejected() -> None:
    """A quotation absent from the source is the clearest confabulation signal."""
    with pytest.raises(MergedResponseError, match="relevance_evidence is not a verbatim"):
        parse_merged_response(
            _response(relevance_evidence="builds quantum compilers"),
            description=DESCRIPTION,
            location_requested=False,
        )


def test_empty_evidence_is_permitted_rather_than_invented() -> None:
    """The prompt tells the model to return "" instead of inventing a quote."""
    judgment = parse_merged_response(
        _response(relevance_evidence=""), description=DESCRIPTION, location_requested=False
    )

    assert judgment.relevance_evidence == ""


def test_a_missing_work_summary_is_rejected() -> None:
    """The summary is written first so it informs the verdicts; it is not optional."""
    with pytest.raises(MergedResponseError, match="work_summary"):
        parse_merged_response(
            _response(work_summary=" "), description=DESCRIPTION, location_requested=False
        )


@pytest.mark.parametrize("fit", list(LocationFit))
def test_location_judgment_round_trips_when_requested(fit: LocationFit) -> None:
    judgment = parse_merged_response(
        _response(
            location_fit=fit.value,
            location_evidence="This role may be performed remotely from India",
            location_reason="Explicitly open to India.",
        ),
        description=DESCRIPTION,
        location_requested=True,
    )

    assert judgment.location_requested is True
    assert judgment.location_fit is fit


def test_location_evidence_may_quote_the_source_location_string() -> None:
    judgment = parse_merged_response(
        _response(
            location_fit="open_remote",
            location_evidence="Remote - APAC",
            location_reason="Open across APAC.",
        ),
        description=DESCRIPTION,
        location_requested=True,
        location_original="Remote - APAC",
    )

    assert judgment.location_evidence == "Remote - APAC"


def test_an_unknown_location_fit_is_rejected() -> None:
    with pytest.raises(MergedResponseError, match="location_fit must be"):
        parse_merged_response(
            _response(location_fit=True, location_evidence="", location_reason="Open."),
            description=DESCRIPTION,
            location_requested=True,
        )


def test_unrequested_location_answer_is_rejected() -> None:
    """The deterministic decision stays authoritative (2.5)."""
    with pytest.raises(MergedResponseError, match="location was not requested"):
        parse_merged_response(
            _response(
                location_fit="india",
                location_evidence="remotely from India",
                location_reason="Open to India.",
            ),
            description=DESCRIPTION,
            location_requested=False,
        )


def test_missing_location_fields_when_requested_are_rejected() -> None:
    with pytest.raises(MergedResponseError):
        parse_merged_response(_response(), description=DESCRIPTION, location_requested=True)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, False),
        ({"relevance": "ai_involved"}, False),
        ({"relevance": "uncertain"}, False),
        ({"seniority_match": "uncertain"}, False),
        ({"relevance": "not_ai"}, True),
        ({"seniority_match": False}, True),
    ],
)
def test_only_confident_rejections_may_drop_a_row(
    overrides: dict[str, object], expected: bool
) -> None:
    """2.6: nothing except a confident rejection is ever dropped.

    ai_involved and uncertain must display, tiered lower. Forcing them into a binary would
    hide the uncertainty rather than remove it, and lose the signal showing which rows
    deserve a click.
    """
    judgment = parse_merged_response(
        _response(**overrides), description=DESCRIPTION, location_requested=False
    )

    assert judgment.is_confident_rejection is expected


@pytest.mark.parametrize(
    ("fit", "expected"),
    [("uncertain", False), ("relocation", False), ("open_remote", False), ("excluded", True)],
)
def test_only_an_excluded_location_drops_a_row(fit: str, expected: bool) -> None:
    judgment = parse_merged_response(
        _response(
            location_fit=fit,
            location_evidence="",
            location_reason="The description does not resolve geography.",
        ),
        description=DESCRIPTION,
        location_requested=True,
    )

    assert judgment.is_confident_rejection is expected


def test_relevance_tiers_and_seniority_values_are_enforced() -> None:
    for legacy in ("maybe", "substantive", "peripheral", "unrelated"):
        with pytest.raises(MergedResponseError, match="relevance must be one of"):
            parse_merged_response(
                _response(relevance=legacy), description=DESCRIPTION, location_requested=False
            )
    with pytest.raises(MergedResponseError, match="seniority_match must be"):
        parse_merged_response(
            _response(seniority_match="probably"),
            description=DESCRIPTION,
            location_requested=False,
        )


def test_malformed_response_is_rejected() -> None:
    with pytest.raises(MergedResponseError, match="not valid JSON"):
        parse_merged_response("not json at all", description=DESCRIPTION, location_requested=False)
    with pytest.raises(MergedResponseError, match="must be a JSON object"):
        parse_merged_response("[1, 2]", description=DESCRIPTION, location_requested=False)


def test_single_purpose_seniority_prompt_is_still_available() -> None:
    """The merged prompt is an addition, not a replacement.

    Keeping the tuned single-purpose path switchable means a regression in the merged
    seniority judgment does not require a code change to back out.
    """
    from job_finder.matching.prompt import load_seniority_prompt

    fallback = load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml")

    assert fallback.prompt_version
    assert (ROOT / "config" / "seniority_prompt.toml").exists()


def test_evidence_may_be_quoted_from_the_title() -> None:
    """Found by running against the real model, not by inspection.

    When a description states no experience requirement the model correctly answers
    ``uncertain`` and then, asked for evidence, quotes the job title -- which is in the
    prompt and is reasonable. Validating against the description alone rejected the entire
    response, so one unquotable sub-judgment destroyed two sound ones. That is precisely
    the collapse 2.5 exists to prevent, so the check spans every text the model was shown.
    """
    judgment = parse_merged_response(
        _response(
            seniority_match="uncertain",
            seniority_evidence="Staff ML Compiler Engineer",
            seniority_reason="No experience requirement is stated.",
        ),
        description=DESCRIPTION,
        title="Staff ML Compiler Engineer, TPU Performance Optimizations",
        location_requested=False,
    )

    assert judgment.seniority_match == "uncertain"
    assert judgment.seniority_evidence == "Staff ML Compiler Engineer"
    # The relevance judgment survives intact rather than being discarded with it.
    assert judgment.relevance is RelevanceTier.CORE_AI


def test_evidence_from_neither_title_nor_description_is_still_rejected() -> None:
    """The confabulation guard must not be weakened by the title allowance."""
    with pytest.raises(MergedResponseError, match="not a verbatim excerpt"):
        parse_merged_response(
            _response(seniority_evidence="requires a PhD in astrophysics"),
            description=DESCRIPTION,
            title="Staff ML Compiler Engineer",
            location_requested=False,
        )


def test_evidence_matching_ignores_whitespace_shape() -> None:
    """Observed live at roughly 1 in 10 calls.

    The model reproduces the wording exactly but collapses a newline to a space or drops a
    double space. Under a strict check that discarded all three judgments over a
    difference that changes no meaning.
    """
    description = "Own model serving.\nRequires 3+ years  of relevant experience."

    judgment = parse_merged_response(
        _response(
            relevance_evidence="Own model serving.",
            seniority_evidence="Requires 3+ years of relevant experience.",
        ),
        description=description,
        location_requested=False,
    )

    assert judgment.seniority_evidence == "Requires 3+ years of relevant experience."


def test_evidence_matching_folds_typographic_variants() -> None:
    """Observed live on gpt-6-luna: the posting used U+2011 (non-breaking hyphen) and the
    model copied it as an ASCII hyphen, failing the check and the identical retry."""
    description = (
        "Experience 0–2 years of experience in analytics, data science, model "
        "development, validation, or big‑data workstreams. Master’s preferred."
    )

    judgment = parse_merged_response(
        _response(
            relevance_evidence="Master's preferred",
            seniority_evidence=(
                "0-2 years of experience in analytics, data science, model development, "
                "validation, or big-data workstreams."
            ),
        ),
        description=description,
        location_requested=False,
    )

    # The model's own text is kept; only the comparison is normalized.
    assert judgment.seniority_evidence.startswith("0-2 years")


def test_evidence_matching_ignores_an_added_closing_period() -> None:
    """Observed live: the source line ends at a bullet and the model adds a period."""
    description = (
        "• 7+ years of analog/mixed-signal IC design experience with deep expertise in "
        "power management • Strong hands-on experience designing at least one PMIC."
    )

    judgment = parse_merged_response(
        _response(
            relevance_evidence="Strong hands-on experience designing at least one PMIC",
            seniority_evidence=(
                "7+ years of analog/mixed-signal IC design experience with deep expertise "
                "in power management."
            ),
        ),
        description=description,
        location_requested=False,
    )

    assert judgment.seniority_evidence.endswith("power management.")


@pytest.mark.parametrize(
    "evidence",
    [
        # interior punctuation still matters: "/" is not a space
        "7+ years of analog mixed-signal IC design experience",
        # punctuation alone is not a quotation
        ".",
    ],
)
def test_typography_folding_does_not_loosen_wording(evidence: str) -> None:
    description = "7+ years of analog/mixed-signal IC design experience."

    with pytest.raises(MergedResponseError, match="not a verbatim excerpt"):
        parse_merged_response(
            _response(relevance_evidence="", seniority_evidence=evidence),
            description=description,
            location_requested=False,
        )


def test_paraphrase_is_still_rejected_after_whitespace_normalization() -> None:
    """The loosening must not weaken the confabulation guard.

    Normalizing whitespace is not normalizing wording -- a reworded quote still fails,
    which is what makes evidence meaningful rather than decorative.
    """
    description = "Own model serving. Requires 3+ years of relevant experience."

    with pytest.raises(MergedResponseError, match="not a verbatim excerpt"):
        parse_merged_response(
            _response(seniority_evidence="needs three or more years of experience"),
            description=description,
            location_requested=False,
        )
