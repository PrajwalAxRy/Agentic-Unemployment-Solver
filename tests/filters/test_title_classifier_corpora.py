"""Corpus regression suite for the title classifier (to_change.md 2.2a).

Promoted from prototypes/ into the test suite when the classifier was integrated, so the
validation that justified the design keeps running on every change rather than only when
someone remembers to invoke a script.

Three layers:
  1. Hand-written cases — every one derives from a real bug found during review.
  2. Live corpora — 1,300 Amazon India + 1,120 Greenhouse titles; asserts zero
     false negatives (an engineering role wrongly rejected).
  3. Regression — every title that passed the OLD stricter filter in the real
     2026-09-29 scan must still pass. Any failure here is a hard regression.
"""

import json
from pathlib import Path

import pytest

from job_finder.filters.title_classifier import classify

ROOT = Path(__file__).resolve().parents[2]
CORPORA = ROOT / "tests" / "fixtures" / "title_corpora"

# --- Layer 1: hand-written cases -------------------------------------------
# Each entry documents a bug that was actually found and fixed.
CASES = [
    # domain word in title must not kill an engineering role (the original bug)
    ("Machine Learning Engineer, Prime Video Ads CX", "pass"),
    ("Software Dev Engineer II, AWS Healthcare AI", "pass"),
    ("Software Development Engineer, Amazon Customer Service", "pass"),
    ("Software Dev Engineer II, Amazon Marketing Cloud", "pass"),
    ("Security Engineer, Security for Employee and Legal Systems", "pass"),
    ("Software Development Engineer II, Enterprise Engineering", "pass"),
    ("Data Scientist II, EU Prime and Marketing Analytics & Science", "pass"),
    # hard exclusions vs. the engineers who BUILD those systems
    ("Data Annotation Platform SDE II", "pass"),
    ("Model Evaluator Service Engineer", "pass"),
    ("AI Marketing Platform Engineer", "pass"),
    ("AI Account Takeover Detection Engineer", "pass"),
    ("AI Governance Engineer", "pass"),
    ("Data Annotation Tool Lead", "pass"),
    ("Data Labeling Framework Lead", "pass"),
    ("Data Annotator", "reject"),
    ("Data Labeler", "reject"),
    ("AI Evaluator", "reject"),
    ("Prompt Writer", "reject"),
    # strong_eng must scan ALL matches, not just the first
    ("AI Evaluator Test Automation", "pass"),
    ("AI Trainer Simulation Lead", "pass"),
    ("AI Ethicist - Computer Vision", "pass"),
    ("AI Sales Analytics Lead", "pass"),
    # semiconductor / embedded — bare "designer"/"driver" must not be blocked
    ("RTL Designer", "pass"),
    ("SoC Designer, Silicon", "pass"),
    ("Analog Design Lead", "pass"),
    ("Linux Device Driver Lead", "pass"),
    ("Flight Controller Software Lead", "pass"),
    ("Python Interpreter Lead", "pass"),
    ("Wireless Communications Lead", "pass"),
    ("Functional Safety Specialist - ISO 26262", "pass"),
    # ...but real design/ops roles still reject
    ("Graphic Designer", "reject"),
    ("UX Designer", "reject"),
    ("Delivery Driver", "reject"),
    ("Financial Controller", "reject"),
    ("Marketing Communications Manager", "reject"),
    ("Warehouse Picker", "reject"),
    # domain qualifiers rescued by a technical noun
    ("NLP Lead - Legal", "pass"),
    ("Analytics Lead - Tax", "pass"),
    ("GenAI Practice Lead, Compliance", "pass"),
    ("Marketing Analytics Lead", "pass"),
    ("Talent Acquisition Data Lead", "pass"),
    ("Buyer Intelligence Lead", "pass"),
    ("Fraud Detection Lead, Claims", "pass"),
    ("Underwriting Risk Scoring Lead", "pass"),
    ("Marketing Attribution Lead", "pass"),
    ("Tax Technology Lead", "pass"),
    ("SEO Crawler Lead", "pass"),
    # ...but bare domain roles reject
    ("Tax Manager", "reject"),
    ("Compliance Analyst", "reject"),
    ("Marketing Manager", "reject"),
    ("Category Manager", "reject"),
    ("Payroll Lead", "reject"),
    ("Senior Financial Analyst, SPS Finance", "reject"),
    # plural abbreviations (inflection length gate was too strict at >=5)
    ("Senior SDETs - Compliance", "pass"),
    ("SREs - Revenue", "pass"),
    ("MLEs - Marketing", "pass"),
    ("LLMs Lead - Legal", "pass"),
    ("Testing Lead - Tax", "pass"),
    # singular/plural technical nouns must behave identically
    ("Risk Analyst - Credit Model", "pass"),
    ("Risk Analyst - Credit Models", "pass"),
    ("Claims Classifiers Lead", "pass"),
    ("Tax Datasets Lead", "pass"),
    # titles with no conventional function word
    ("Member of Technical Staff", "pass"),
    ("MTS - Distributed Systems", "pass"),
    ("Head of AI", "pass"),
    ("Deep Learning Lead - Medical Imaging", "pass"),
    ("Perception Engineer, ADAS", "pass"),
    ("Quantitative Researcher", "pass"),
    ("Speech Scientist", "pass"),
    ("SDE-2, Flipkart Search", "pass"),
    # clear non-engineering
    ("Account Executive, Enterprise", "reject"),
    ("Sales Development Representative", "reject"),
    ("Recruiting Coordinator", "reject"),
    ("Executive Assistant", "reject"),
    ("Warehouse Associate", "reject"),
    ("Area Manager, Operations", "reject"),
    ("Delivery Station Customer Service Associate", "reject"),
]

# Words implying an engineering role; used to detect false negatives in bulk data.
ENGINEERING_SIGNALS = (
    "engineer",
    "developer",
    " scientist",
    "architect",
    "sde ",
    "programmer",
    "machine learning",
    "analytics",
    "data analyst",
)


@pytest.mark.parametrize(("title", "expected"), CASES, ids=[t for t, _ in CASES])
def test_hand_written_case(title: str, expected: str) -> None:
    """Every case derives from a real bug found during adversarial review."""
    decision, reason_code, matched = classify(title)
    assert decision == expected, f"{title!r} -> {decision} via {reason_code} ({matched})"


@pytest.mark.parametrize(
    ("name", "filename", "minimum_pass_rate"),
    [
        ("Amazon India", "amazon_india_titles.json", 70),
        ("Greenhouse", "greenhouse_titles.json", 60),
    ],
)
def test_live_corpus_has_no_false_negatives(
    name: str, filename: str, minimum_pass_rate: int
) -> None:
    """Zero engineering roles wrongly rejected across ~2,400 real titles.

    A false negative here is invisible in production -- the job is never fetched, never
    seen, never counted. A false positive costs one skim. That asymmetry is why this
    asserts zero false negatives but only a floor on the pass rate.
    """
    titles = [item["title"] for item in json.loads((CORPORA / filename).read_text("utf-8"))]
    results = [(title, classify(title)) for title in titles]

    false_negatives = [
        (title, verdict)
        for title, verdict in results
        if verdict[0] == "reject"
        and any(signal in f" {title.lower()} " for signal in ENGINEERING_SIGNALS)
    ]
    assert not false_negatives, (
        f"{name}: {len(false_negatives)} engineering titles wrongly rejected, "
        f"first few: {false_negatives[:5]}"
    )

    passed = sum(1 for _, verdict in results if verdict[0] == "pass")
    pass_rate = 100 * passed // len(results)
    assert pass_rate >= minimum_pass_rate, (
        f"{name} pass rate fell to {pass_rate}% (floor {minimum_pass_rate}%); "
        "a sharp drop means the filter has become strict again"
    )


def test_no_regression_against_the_real_scan() -> None:
    """Every title that passed the OLD stricter filter must still pass.

    This is the guard against over-correction: the obvious way to break a filter rewrite
    is to fix the false positives and quietly lose the true ones.
    """
    report_path = ROOT / "reports" / "latest_scan.json"
    if not report_path.exists():  # pragma: no cover - depends on local artifacts
        pytest.skip("reports/latest_scan.json is not present")

    report = json.loads(report_path.read_text("utf-8"))
    known = [row["title"] for row in report["review_candidates"]]
    known += [row["title"] for row in report["matching_jobs"] + report["date_uncertain_jobs"]]

    regressions = [(title, classify(title)) for title in known if classify(title)[0] != "pass"]

    assert not regressions, f"{len(regressions)} titles regressed: {regressions[:5]}"
