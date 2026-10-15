"""Select the 1,000-job benchmark from the 2026-10-05 batch (policy v1.1, step 3).

  LAB_BATCH=2026-10-05 uv run --locked python experiments/llm_compare/lab/bench_sets.py

Excludes every posting already used in earlier rounds: hand verdicts (10-02/03/04),
casebook jobs (which prompt v9's worked examples paraphrase), and the effort500 set that
v9 was scored and diagnosed on. Matched on company+title+description, because most
postings stay live across batches under new ordinals.

Selection uses text features only, never model answers:
- hard (~200): every unresolved-location job, every empty-description job, then jobs whose
  text mixes signals (AI words in the body but not the title, consulting/product/analyst/
  architect titles with AI words, AI/ML titles), spread evenly over those kinds;
- random (~800): a seeded uniform sample of the remaining unused jobs.
Both are then split into a tuning half and a sealed test half, stratified by kind.
Deterministic: the same batch always gives the same sets.
"""

import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

TOTAL, HARD = 1000, 200
rng = random.Random(20261006)
LABDIR = lab.HERE

AI_TITLE = re.compile(
    r"\b(ai|ml|genai|gen ai|llm|machine learning|deep learning|data scien\w*|nlp|"
    r"computer vision|vision|perception|speech|applied scien\w*|research scien\w*|"
    r"inference|mlops|agentic|agents?)\b",
    re.I,
)
AI_BODY = re.compile(
    r"\b(machine learning|deep learning|llms?|generative ai|genai|\bai\b|artificial "
    r"intelligence|rag|computer vision|nlp|agentic|neural|model training|fine-?tun\w*)\b",
    re.I,
)
GREY_TITLE = re.compile(
    r"\b(consult\w*|architect|product (manager|owner|lead)|program|strategy|analyst|"
    r"customer|solutions?|success|sales|presales|governance|risk|security|quality|"
    r"designer|director|head|manager)\b",
    re.I,
)


def fingerprint(case: dict) -> str:
    text = case["company"] + case["title"] + case["description"]
    return hashlib.sha256(text.encode()).hexdigest()


def load(name: str) -> dict[int, dict]:
    raw = json.loads((LABDIR / name).read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def used_fingerprints() -> set[str]:
    used: set[str] = set()
    batches = {
        "10-02": ("cases.json", "truth.json"),
        "10-03": ("cases_2026-10-03.json", "truth_2026-10-03.json"),
        "10-04": ("cases_2026-10-04.json", "truth_2026-10-04.json"),
    }
    cases = {}
    for label, (cases_file, truth_file) in batches.items():
        cases[label] = load(cases_file)
        for o in load(truth_file):
            if o in cases[label]:
                used.add(fingerprint(cases[label][o]))
    effort500 = json.loads((LABDIR / "sets_2026-10-04.json").read_text())["effort500"]
    used |= {fingerprint(cases["10-04"][o]) for o in effort500}
    groups = json.loads((LABDIR.parent / "casebook" / "groups_v0.json").read_text("utf-8"))
    for group in groups["types"]:
        for ref in group["anchors"] + group["members"]:
            label, o = ref.split(":")
            used.add(fingerprint(cases[label][int(o)]))
    return used


def kind(case: dict) -> str | None:
    """The hard-set bucket a job falls in, or None for an ordinary job."""
    if case["location_original"] is not None:
        return "location"
    if not case.get("has_description", True):
        return "no_description"
    title, body = case["title"], case["description"]
    if AI_TITLE.search(title):
        return "ai_title"
    if AI_BODY.search(body):
        return "grey_title_ai_body" if GREY_TITLE.search(title) else "ai_body_only"
    return None


cases = lab.load_cases()
used = used_fingerprints()
# One ordinal per posting: duplicate postings would double-count in scores.
seen, pool = set(), []
for o in sorted(cases):
    fp = fingerprint(cases[o])
    if fp in used or fp in seen:
        continue
    seen.add(fp)
    pool.append(o)

buckets: dict[str, list[int]] = {}
for o in pool:
    k = kind(cases[o])
    if k:
        buckets.setdefault(k, []).append(o)
hard: list[int] = []
hard += buckets.get("location", []) + buckets.get("no_description", [])
mixed = ["ai_title", "grey_title_ai_body", "ai_body_only"]
for k in mixed:
    rng.shuffle(buckets.get(k, []))
while len(hard) < HARD and any(buckets.get(k) for k in mixed):
    for k in mixed:
        if buckets.get(k) and len(hard) < HARD:
            hard.append(buckets[k].pop())
hard_set = set(hard)
rest = [o for o in pool if o not in hard_set]
random_part = rng.sample(rest, TOTAL - len(hard))

kinds = {o: (kind(cases[o]) or "plain") for o in hard}
kinds |= {o: "random" for o in random_part}
tune, test = [], []
by_kind: dict[str, list[int]] = {}
for o, k in kinds.items():
    by_kind.setdefault(k, []).append(o)
for _kind, members in sorted(by_kind.items()):
    members = sorted(members)
    rng.shuffle(members)
    half = len(members) // 2
    tune += members[:half]
    test += members[half:]

sets = json.loads(lab.SETS.read_text(encoding="utf-8")) if lab.SETS.exists() else {}
sets |= {
    "bench1000": sorted(kinds),
    "bench_tune": sorted(tune),
    "bench_test": sorted(test),
    "bench_hard": sorted(hard),
    "bench_random": sorted(random_part),
}
lab.SETS.write_text(json.dumps(sets))
(LABDIR / "bench_kinds_2026-10-05.json").write_text(
    json.dumps({str(o): k for o, k in kinds.items()})
)
print(f"batch {len(cases)} jobs; unused unique postings {len(pool)}")
print(
    f"hard {len(hard)}: "
    + ", ".join(
        f"{k} {sum(v == k for v in kinds.values())}" for k in ["location", "no_description", *mixed]
    )
)
print(f"random {len(random_part)}; tuning {len(tune)}, sealed test {len(test)}")
