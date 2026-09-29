"""Regression suite for the generous title filter.

Run:  python3 prototypes/test_title_filter.py

Three layers:
  1. Hand-written cases — every one derives from a real bug found during review.
  2. Live corpora — 1,300 Amazon India + 1,120 Greenhouse titles; asserts zero
     false negatives (an engineering role wrongly rejected).
  3. Regression — every title that passed the OLD stricter filter in the real
     2026-09-29 scan must still pass. Any failure here is a hard regression.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from title_filter import classify  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

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
    "engineer", "developer", " scientist", "architect", "sde ",
    "programmer", "machine learning", "analytics", "data analyst",
)


def run() -> int:
    failures = 0

    print("=" * 62)
    print("Layer 1: hand-written cases")
    bad = [(t, e, classify(t)) for t, e in CASES if classify(t)[0] != e]
    print(f"  {len(CASES) - len(bad)}/{len(CASES)} correct")
    for title, expected, got in bad:
        print(f"    WANT {expected:6s} GOT {got[0]:6s} [{got[1]}/{got[2]}]  {title}")
    failures += len(bad)

    print("\nLayer 2: live corpora — false-negative check")
    for name, fname in (("Amazon India", "raw_titles.json"), ("Greenhouse", "gh_titles.json")):
        path = os.path.join(HERE, fname)
        if not os.path.exists(path):
            print(f"  {name}: SKIPPED (missing {fname})")
            continue
        titles = [x["title"] for x in json.load(open(path))]
        results = [(t, classify(t)) for t in titles]
        passed = [r for r in results if r[1][0] == "pass"]
        fn = [
            (t, v) for t, v in results
            if v[0] == "reject" and any(w in (" " + t.lower() + " ") for w in ENGINEERING_SIGNALS)
        ]
        pct = 100 * len(passed) // len(results)
        print(f"  {name}: pass {len(passed)}/{len(results)} ({pct}%)  false-negatives {len(fn)}")
        for t, v in fn[:10]:
            print(f"    FN: {t[:66]}  [{v[2]}]")
        failures += len(fn)

    print("\nLayer 3: regression vs the real 2026-09-29 scan")
    report = os.path.join(ROOT, "reports", "latest_scan.json")
    if os.path.exists(report):
        d = json.load(open(report))
        known = [r["title"] for r in d["review_candidates"]]
        known += [r["title"] for r in d["matching_jobs"] + d["date_uncertain_jobs"]]
        regressions = [(t, classify(t)) for t in known if classify(t)[0] != "pass"]
        print(f"  {len(known) - len(regressions)}/{len(known)} still pass")
        for t, v in regressions:
            print(f"    REGRESSION: {t[:66]}  [{v[1]}/{v[2]}]")
        failures += len(regressions)
    else:
        print("  SKIPPED (no reports/latest_scan.json)")

    print("=" * 62)
    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
