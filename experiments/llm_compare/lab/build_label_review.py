"""Build label_review.html: an offline page for checking Claude's blind benchmark labels.

  python experiments/llm_compare/lab/build_label_review.py

Shows every label at confidence 5 or lower, then a seeded random sample of 50 labels at
6 or higher (the error-rate check: if more than ~10% of those change, relabel more widely).
No model answers appear anywhere. The page saves choices in the browser and exports
label_review_2026-10-05.json. Stdlib only; reads the git-ignored cases file.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCH = "2026-10-05"
LOW_CONFIDENCE = 5
SAMPLE_SIZE = 50
SEED = 20261006


def load_labels() -> dict[int, dict]:
    labels = {}
    for line in (HERE / f"labels_{BATCH}.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        ordinal, relevance, seniority, location, conf, reason = line.split("|", 5)
        labels[int(ordinal)] = {
            "relevance": relevance,
            "seniority": seniority,
            "location": location,
            "conf": int(conf),
            "reason": reason,
        }
    return labels


def main() -> None:
    labels = load_labels()
    cases = {
        int(k): v
        for k, v in json.loads((HERE / f"cases_{BATCH}.json").read_text(encoding="utf-8")).items()
    }
    sets = json.loads((HERE / f"sets_{BATCH}.json").read_text(encoding="utf-8"))
    half = {o: "tune" for o in sets["bench_tune"]} | {o: "test" for o in sets["bench_test"]}

    rng = random.Random(SEED)
    low = sorted(o for o, label in labels.items() if label["conf"] <= LOW_CONFIDENCE)
    rng.shuffle(low)
    confident = sorted(o for o, label in labels.items() if label["conf"] > LOW_CONFIDENCE)
    sample = rng.sample(confident, SAMPLE_SIZE)

    jobs = []
    for section, ordinals in (("low", low), ("sample", sample)):
        for o in ordinals:
            case = cases[o]
            jobs.append(
                {
                    "ordinal": o,
                    "section": section,
                    "half": half.get(o, "?"),
                    "company": case["company"],
                    "title": case["title"],
                    "location": case.get("location_original"),
                    "description": " ".join(case["description"].split()),
                    "label": labels[o],
                }
            )

    payload = json.dumps({"batch": BATCH, "jobs": jobs}, ensure_ascii=False)
    html = (HERE / "label_review_template.html").read_text(encoding="utf-8")
    out = HERE / "label_review.html"
    out.write_text(
        html.replace("/*__DATA__*/null", payload.replace("</", "<\\/")), encoding="utf-8"
    )
    print(
        f"wrote {out} ({out.stat().st_size // 1024} KB): "
        f"{len(low)} low-confidence + {len(sample)} sampled = {len(jobs)} jobs"
    )


if __name__ == "__main__":
    main()
