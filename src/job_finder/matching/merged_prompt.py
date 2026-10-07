"""Merged relevance + seniority + location prompt and response contract.

``to_change.md`` 2.5 collapses three judgments into one call per job, cached on
``description_hash``. The saving is real -- the description is the expensive part of the
payload and it is sent once instead of three times -- but the requirement that makes this
safe is the one that is easy to skip:

    Structured schema, separate field and verbatim quote per judgment so a failing
    sub-judgment is diagnosable.

Merging the *call* must not merge the *diagnostics*. If a single verdict came back with a
single justification, a relevance misfire and a seniority misfire would be
indistinguishable -- the same class of collapse that made the title-normalization bug
invisible for 97 rows (1.1).

The location judgment is conditional. When the deterministic filter already resolved the
location, the field is omitted from both the request and the response: 2.5 is explicit
that cheap deterministic rejections still happen before the model, and asking a question
that is already answered invites the model to contradict it.

``config/seniority_prompt.toml`` and :mod:`job_finder.matching.prompt` are deliberately
left in place. This is an addition, not a replacement, so the tuned single-purpose path
remains available as a fallback without a code change.

Schema version 2 (prompt 2.0.0, 2026-10-06) replaced the three relevance verdicts and the
boolean location answer with the contract measured in ``experiments/llm_compare``
(``bench_2026-10-05_report.md``): four relevance tiers, a one-sentence ``work_summary``
written before the verdicts, and a five-way ``location_fit``. Version 1 prompts are refused
rather than mapped: the request fingerprint changes anyway, so nothing cached under 1.x is
reused, and one vocabulary keeps every consumer simple.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from job_finder.matching.seniority import DetectedLevel, SeniorityMatch

SCHEMA_VERSION = 2


class RelevanceTier(StrEnum):
    """Is this person doing AI/ML work? (screening policy v1.2, section 4)."""

    CORE_AI = "core_ai"
    """AI/ML is the main work."""
    AI_INVOLVED = "ai_involved"
    """AI/ML is an explicit, real part of the job, though not all of it."""
    UNCERTAIN = "uncertain"
    """AI/ML is in the picture but it is unclear this person does it: shown, tagged."""
    NOT_AI = "not_ai"
    """AI absent or only setting, tooling or decoration: hidden."""

    @property
    def shown(self) -> bool:
        return self is not RelevanceTier.NOT_AI


class LocationFit(StrEnum):
    """Can a candidate in India take this job? Asked only when the filter could not tell."""

    INDIA = "india"
    OPEN_REMOTE = "open_remote"
    RELOCATION = "relocation"
    """Based abroad but offers relocation or sponsorship: shown in its own category."""
    EXCLUDED = "excluded"
    UNCERTAIN = "uncertain"


class MergedResponseError(ValueError):
    """The model's merged response did not satisfy the contract."""


@dataclass(frozen=True, slots=True)
class MergedJudgment:
    """One job's three-part judgment.

    Every judgment keeps its own verdict, evidence and reason. 2.6 requires graded
    verdicts throughout: nothing except a confident rejection is dropped, and a displayed
    ``uncertain`` is the system working rather than failing.
    """

    work_summary: str
    """One sentence on what the person would actually do, written before the verdicts."""

    relevance: RelevanceTier
    relevance_evidence: str
    relevance_reason: str

    seniority_match: SeniorityMatch
    detected_level: DetectedLevel
    required_experience: str
    seniority_evidence: str
    seniority_reason: str

    location_fit: LocationFit | None = None
    location_evidence: str | None = None
    location_reason: str | None = None

    @property
    def location_requested(self) -> bool:
        return self.location_fit is not None

    @property
    def is_confident_rejection(self) -> bool:
        """Whether this row may be dropped rather than displayed.

        The only three conditions that drop a row (2.6). Everything else -- uncertain
        relevance, uncertain seniority, uncertain location, relocation -- displays.
        """
        return (
            self.relevance is RelevanceTier.NOT_AI
            or self.seniority_match is False
            or self.location_fit is LocationFit.EXCLUDED
        )


@dataclass(frozen=True, slots=True)
class MergedPrompt:
    """Validated merged prompt text and stable version."""

    schema_version: int
    prompt_version: str
    system_prompt: str
    user_prompt_template: str
    location_section_template: str

    def render(
        self,
        *,
        title: str,
        description: str,
        target_description: str,
        location_original: str | None = None,
    ) -> str:
        """Render the user prompt, including the location section only when needed."""
        location_section = ""
        if location_original is not None:
            location_section = self.location_section_template.format(
                location_original=_required_text(location_original, "location_original")
            )
        return self.user_prompt_template.format(
            title=_required_text(title, "title"),
            description=_required_text(description, "description"),
            target_description=_required_text(target_description, "target_description"),
            location_section=location_section,
        )


def load_merged_prompt(path: Path) -> MergedPrompt:
    """Load and validate the versioned merged prompt."""
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    schema_version = raw.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported merged prompt schema_version: {schema_version!r}")
    prompt = MergedPrompt(
        schema_version=schema_version,
        prompt_version=_required_text(raw.get("prompt_version"), "prompt_version"),
        system_prompt=_required_text(raw.get("system_prompt"), "system_prompt"),
        user_prompt_template=_required_text(
            raw.get("user_prompt_template"), "user_prompt_template"
        ),
        location_section_template=_required_text(
            raw.get("location_section_template"), "location_section_template"
        ),
    )
    for placeholder in ("{title}", "{description}", "{target_description}", "{location_section}"):
        if placeholder not in prompt.user_prompt_template:
            raise ValueError(f"user_prompt_template must contain {placeholder}")
    if "{location_original}" not in prompt.location_section_template:
        raise ValueError("location_section_template must contain {location_original}")
    return prompt


def parse_merged_response(
    content: str,
    *,
    description: str,
    location_requested: bool,
    title: str = "",
    location_original: str | None = None,
) -> MergedJudgment:
    """Parse and validate a merged response.

    Evidence is checked against the text the model was actually given -- the description
    **and the title**, since both are in the prompt. A quotation from neither is the
    clearest available signal that a judgment was confabulated.

    Including the title is not a loosening; it is a correctness fix found by running this
    against the real model. When a description states no experience requirement, the model
    correctly answers ``uncertain`` and then, asked for evidence, quotes the title. Under
    a description-only check that discarded the whole response -- so one unquotable
    sub-judgment destroyed two sound ones, which is exactly the collapse 2.5 exists to
    prevent. Evidence is still required to be verbatim from the prompt; it simply may come
    from either field the model was shown.
    """
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as error:
        raise MergedResponseError("merged response was not valid JSON") from error
    if not isinstance(raw, Mapping):
        raise MergedResponseError("merged response must be a JSON object")

    sources = (description, title) if title else (description,)

    work_summary = _required_text(raw.get("work_summary"), "work_summary")
    relevance = _relevance(raw.get("relevance"))
    relevance_evidence = _evidence(raw, "relevance_evidence", sources)
    seniority_match = _seniority_match(raw.get("seniority_match"))
    seniority_evidence = _evidence(raw, "seniority_evidence", sources)

    location_fit: LocationFit | None = None
    location_evidence: str | None = None
    location_reason: str | None = None
    if location_requested:
        location_fit = _location_fit(raw.get("location_fit"))
        # The source's location string is shown to the model in its own prompt section, so
        # it is a legitimate quotation for the location judgment (and only for that one).
        location_sources = (*sources, location_original) if location_original else sources
        location_evidence = _evidence(raw, "location_evidence", location_sources)
        location_reason = _required_text(raw.get("location_reason"), "location_reason")
    elif "location_fit" in raw:
        # The model answered a question it was not asked. Refusing it keeps the
        # deterministic decision authoritative, per 2.5.
        raise MergedResponseError(
            "merged response contains location_fit but location was not requested"
        )

    return MergedJudgment(
        work_summary=work_summary,
        relevance=relevance,
        relevance_evidence=relevance_evidence,
        relevance_reason=_required_text(raw.get("relevance_reason"), "relevance_reason"),
        seniority_match=seniority_match,
        detected_level=_detected_level(raw.get("detected_level")),
        required_experience=_required_text(raw.get("required_experience"), "required_experience"),
        seniority_evidence=seniority_evidence,
        seniority_reason=_required_text(raw.get("seniority_reason"), "seniority_reason"),
        location_fit=location_fit,
        location_evidence=location_evidence,
        location_reason=location_reason,
    )


def _relevance(value: object) -> RelevanceTier:
    if not isinstance(value, str):
        raise MergedResponseError("relevance must be a string")
    try:
        return RelevanceTier(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in RelevanceTier)
        raise MergedResponseError(f"relevance must be one of: {supported}") from error


def _seniority_match(value: object) -> SeniorityMatch:
    if isinstance(value, bool):
        return value
    if value == "uncertain":
        return "uncertain"
    raise MergedResponseError("seniority_match must be true, false, or 'uncertain'")


def _location_fit(value: object) -> LocationFit:
    if not isinstance(value, str):
        raise MergedResponseError("location_fit must be a string")
    try:
        return LocationFit(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in LocationFit)
        raise MergedResponseError(f"location_fit must be one of: {supported}") from error


def _detected_level(value: object) -> DetectedLevel:
    if not isinstance(value, str):
        raise MergedResponseError("detected_level must be a string")
    try:
        return DetectedLevel(value)
    except ValueError as error:
        raise MergedResponseError("detected_level is not a supported level") from error


def _evidence(raw: Mapping[str, object], key: str, sources: tuple[str, ...]) -> str:
    """Validate one evidence field against every text the model was shown."""
    value = raw.get(key)
    if not isinstance(value, str):
        raise MergedResponseError(f"{key} must be a string")
    excerpt = value.strip()
    if not excerpt:
        # Explicitly permitted: the prompt tells the model to return an empty string
        # rather than invent a quotation when the prompt supports nothing.
        return ""
    if not any(_contains_excerpt(source, excerpt) for source in sources):
        raise MergedResponseError(f"{key} is not a verbatim excerpt of the supplied job text")
    return excerpt


def _contains_excerpt(source: str, excerpt: str) -> bool:
    """Whether ``excerpt`` appears in ``source``, ignoring whitespace shape.

    Observed live at roughly 1 in 10 calls: the model reproduces the wording exactly but
    collapses a newline to a space, or drops a double space. Under a strict check that
    discards the entire response -- three judgments lost to a whitespace difference that
    changes no meaning.

    Case and whitespace are normalized; wording is not. A paraphrase still fails, which is
    the property that makes evidence a confabulation guard rather than decoration.

    Typography and edge punctuation are normalized for the same reason. Observed live with
    a reasoning model: postings write "big-data" with U+2011 (non-breaking hyphen) and the
    model copies it as an ASCII hyphen; or the model ends a quote with a period where the source
    line ends at a bullet. Both rejected correct quotes, failed the paid retry the same
    way, and discarded all three judgments of jobs that should have been shown.
    """
    needle = _collapse(excerpt).strip(_EDGE_PUNCTUATION)
    return bool(needle) and needle in _collapse(source)


# Characters a model routinely regularizes while copying: hyphen and dash variants, curly
# quotes, and non-breaking or invisible spaces. Folding them changes no wording.
_TYPOGRAPHY = str.maketrans(
    {
        # hyphen, non-breaking hyphen, figure/en/em dash, horizontal bar, minus sign
        **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"),
        # curly and low single quotes, reversed single quote, prime
        **dict.fromkeys("\u2018\u2019\u201a\u201b\u2032", "'"),
        # curly and low double quotes, double prime
        **dict.fromkeys("\u201c\u201d\u201e\u2033", '"'),
        # no-break, figure and narrow no-break spaces
        **dict.fromkeys("\u00a0\u2007\u202f", " "),
        # soft hyphen, zero-width space/non-joiner/joiner, word joiner, byte-order mark
        **dict.fromkeys("\u00ad\u200b\u200c\u200d\u2060\ufeff", None),
    }
)
# Stripped from the ends of an excerpt only: a quote that adds or drops a closing period
# or an opening bullet is still the same text. Interior punctuation must still match.
_EDGE_PUNCTUATION = " .,;:\u2022\u00b7"


def _collapse(value: str) -> str:
    return " ".join(value.translate(_TYPOGRAPHY).split()).casefold()


def _required_text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MergedResponseError(f"{path} must be a non-empty string")
    return value.strip()
