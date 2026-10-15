"""Build review.html: an offline page for deciding borderline relevance types.

  uv run --locked python experiments/llm_compare/casebook/build_review.py

Reads groups_v0.json (the grouping), the frozen lab cases and raw replies for each batch,
and the hand verdicts, and writes one self-contained HTML file next to this script. The
page saves choices in the browser and exports casebook_decisions.json. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent / "lab"

# batch label -> (cases file, results dir, truth file, Luna tags, Sol tags), tags in
# preference order: the first tag that has the job supplies its answers.
BATCHES = {
    "10-02": (
        "cases.json",
        "results",
        "truth.json",
        ["luna_v8", "luna_v4", "luna_v4h"],
        ["sol_v4", "sol_v4h"],
    ),
    "10-03": (
        "cases_2026-10-03.json",
        "results_2026-10-03",
        "truth_2026-10-03.json",
        ["luna_v8", "luna_v8_all"],
        ["sol_v4_x", "sol_v4"],
    ),
    "10-04": (
        "cases_2026-10-04.json",
        "results_2026-10-04",
        "truth_2026-10-04.json",
        ["luna13"],
        ["sol13"],
    ),
}
TAG_PROMPT = {
    "luna_v8": "1.3.0",
    "luna_v8_all": "1.3.0",
    "luna13": "1.3.0",
    "luna_v4": "1.2.0",
    "luna_v4h": "1.2.0",
    "sol_v4": "1.2.0",
    "sol_v4h": "1.2.0",
    "sol_v4_x": "1.2.0",
    "sol13": "1.3.0",
}


def load_answers(results_dir: Path, tag: str) -> dict[int, list[dict]]:
    path = results_dir / f"{tag}.jsonl"
    if not path.exists():
        return {}
    answers: dict[int, list[dict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        judgment = record.get("judgment")
        if judgment:
            answers.setdefault(record["ordinal"], []).append(
                {
                    "relevance": judgment["relevance"],
                    "seniority": str(judgment["seniority_match"]),
                    "evidence": judgment["relevance_evidence"],
                    "reason": judgment["relevance_reason"],
                }
            )
    return answers


def model_view(
    tags: list[str], results_dir: Path, cache: dict, ordinal: int, case: dict, fallback_key: str
) -> dict:
    for tag in tags:
        key = (str(results_dir), tag)
        if key not in cache:
            cache[key] = load_answers(results_dir, tag)
        if ordinal in cache[key]:
            return {
                "source": f"{tag} (prompt {TAG_PROMPT.get(tag, '?')})",
                "answers": cache[key][ordinal],
            }
    original = (case.get(fallback_key) or {}).get("judgment")
    if original:  # the original 2026-10-02 pipeline run, prompt 1.1.0
        return {
            "source": "original run (prompt 1.1.0)",
            "answers": [
                {
                    "relevance": original["relevance"],
                    "seniority": str(original["seniority_match"]),
                    "evidence": original.get("relevance_evidence") or "",
                    "reason": original.get("relevance_reason") or "",
                }
            ],
        }
    return {"source": "none", "answers": []}


def main() -> None:
    groups = json.loads((HERE / "groups_v0.json").read_text(encoding="utf-8"))
    cases_by_batch, truth_by_batch, cache = {}, {}, {}
    for batch, (cases_file, _, truth_file, _, _) in BATCHES.items():
        cases_by_batch[batch] = {
            int(k): v for k, v in json.loads((LAB / cases_file).read_text(encoding="utf-8")).items()
        }
        truth_by_batch[batch] = {
            int(k): v for k, v in json.loads((LAB / truth_file).read_text(encoding="utf-8")).items()
        }

    jobs, seen, types = {}, {}, []
    for group in groups["types"]:
        members = []
        for ref in group["anchors"] + group["members"]:
            batch, ordinal_text = ref.split(":")
            ordinal = int(ordinal_text)
            case = cases_by_batch[batch][ordinal]
            # The same posting recurs across batches; show it once, under its first type.
            fingerprint = hashlib.sha256(
                (case["company"] + case["title"] + case["description"]).encode()
            ).hexdigest()
            if fingerprint in seen:
                print(f"  skip duplicate {ref} (same posting as {seen[fingerprint]})")
                continue
            seen[fingerprint] = ref
            _, results_dir, _, luna_tags, sol_tags = BATCHES[batch]
            results_path = LAB / results_dir
            verdict = truth_by_batch[batch].get(ordinal, {})
            jobs[ref] = {
                "id": ref,
                "anchor": ref in group["anchors"],
                "company": case["company"],
                "title": case["title"],
                "location": case.get("location_original"),
                "description": " ".join(case["description"].split()),
                "job_key": case.get("job_key"),
                "claude": {
                    "relevance": verdict.get("relevance"),
                    "conf": verdict.get("conf"),
                    "note": verdict.get("note", ""),
                },
                "luna": model_view(luna_tags, results_path, cache, ordinal, case, "luna0"),
                "sol": model_view(sol_tags, results_path, cache, ordinal, case, "sol0"),
            }
            members.append(ref)
        types.append(
            {k: group[k] for k in ("key", "title", "description", "suggest", "why")}
            | {"jobs": members}
        )

    data = {"version": groups["version"], "types": types, "jobs": jobs}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (HERE / "review_template.html").read_text(encoding="utf-8")
    out = HERE / "review.html"
    out.write_text(html.replace("/*__DATA__*/null", payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB): {len(types)} types, {len(jobs)} jobs")


if __name__ == "__main__":
    main()
