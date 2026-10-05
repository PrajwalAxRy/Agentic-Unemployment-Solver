"""Score benchmark runs on the 1,000-job 2026-10-05 set against truth_bench_2026-10-05.json.

  LAB_BATCH=2026-10-05 python score_bench.py [--half tune|test|both] [--show-test-jobs] TAG ...

Truth is policy v1.2: Claude's blind labels, corrected by the user's review. Primary score
is visibility (policy section 7): a job is shown when relevance is not hide, seniority is
not "no" and, where location was asked, it is not excluded. The core / involved /
uncertain tag is reported but soft.

Answers: prompt 1.x substantive -> core, peripheral -> involved, unrelated -> hide,
location_eligible false -> excluded; prompt 2.x core_ai / ai_involved / uncertain / not_ai
map one to one. Production makes one call per job, so the headline counts average every
recorded call ("per call"); "vote" is the majority over a run's repetitions.

Jobs whose truth came from the user's review changes (source "user", "policy_v1.2") wrote
policy v1.2's new rules, so prompts 1.4.0 and v10 have effectively seen them. They are
scored separately and left out of the headline. Job lists are printed for the tuning half
only; the sealed test half prints counts unless --show-test-jobs (final scoring only).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

TRUTH = lab.HERE / "truth_bench_2026-10-05.json"
REL = {
    "substantive": "core",
    "peripheral": "involved",
    "unrelated": "hide",
    "core_ai": "core",
    "ai_involved": "involved",
    "uncertain": "uncertain",
    "not_ai": "hide",
}
POLICY_SOURCES = {"user", "policy_v1.2"}


def answer(judgment: dict | None) -> dict | None:
    """One call's judgment in truth vocabulary, or None for a failed call."""
    if not judgment:
        return None
    sen = {"True": "yes", "False": "no"}.get(str(judgment["seniority_match"]), "uncertain")
    loc = judgment.get("location_fit")
    if loc is None and "location_eligible" in judgment:
        loc = {"True": "india", "False": "excluded"}.get(
            str(judgment["location_eligible"]), "uncertain"
        )
    return {"relevance": REL[judgment["relevance"]], "seniority": sen, "location": loc or "-"}


def shown_rel(a: dict | None) -> bool:
    return a is not None and a["relevance"] != "hide"


def shown(a: dict | None) -> bool:
    return shown_rel(a) and a["seniority"] != "no" and a["location"] != "excluded"


def majority(answers: list[dict | None], key) -> bool:
    votes = [key(a) for a in answers]
    return sum(votes) * 2 > len(votes) if votes else False


def score_tag(tag: str, truth: dict[int, dict], jobs: list[int], list_jobs: bool) -> list[str]:
    res = lab.load_results(tag)
    jobs = [o for o in jobs if o in res]
    if not jobs:
        return [f"| {tag} | no results |"]
    calls = n_calls = failed = 0
    rel_fn = rel_fp = vis_fn = vis_fp = sen_closed = sen_opened = 0.0
    v_rel_fn, v_rel_fp, v_vis_fn, v_vis_fp, unstable = [], [], [], [], 0
    for o in jobs:
        t = truth[o]
        answers = [answer(r["judgment"]) for r in res[o]]
        n = len(answers)
        n_calls += n
        failed += sum(a is None for a in answers)
        t_rel, t_vis = t["relevance"] != "hide", shown(t)
        rel_fn += sum(t_rel and not shown_rel(a) for a in answers) / n
        rel_fp += sum(not t_rel and shown_rel(a) for a in answers) / n
        vis_fn += sum(t_vis and not shown(a) for a in answers) / n
        vis_fp += sum(not t_vis and shown(a) for a in answers) / n
        if t_rel:
            sen_closed += (
                sum(
                    t["seniority"] != "no" and a is not None and a["seniority"] == "no"
                    for a in answers
                )
                / n
            )
            sen_opened += (
                sum(
                    t["seniority"] == "no" and a is not None and a["seniority"] != "no"
                    for a in answers
                )
                / n
            )
        if len({shown(a) for a in answers}) > 1:
            unstable += 1
        m_rel, m_vis = majority(answers, shown_rel), majority(answers, shown)
        if t_rel and not m_rel:
            v_rel_fn.append(o)
        if m_rel and not t_rel:
            v_rel_fp.append(o)
        if t_vis and not m_vis:
            v_vis_fn.append(o)
        if m_vis and not t_vis:
            v_vis_fp.append(o)
        calls += 1
    reps = n_calls / calls
    row = (
        f"| {tag} | {calls} | {reps:.1f} | {failed} | {rel_fn:.1f} | {rel_fp:.1f} | "
        f"{len(v_rel_fn)} / {len(v_rel_fp)} | {vis_fn:.1f} | {vis_fp:.1f} | "
        f"{len(v_vis_fn)} / {len(v_vis_fp)} | {sen_closed:.1f} | {sen_opened:.1f} | "
        f"{unstable} |"
    )
    lines = [row]
    if list_jobs:
        lines.append(
            f"|  | relevance missed {v_rel_fn} · extra {v_rel_fp} · shown missed "
            f"{v_vis_fn} · shown extra {v_vis_fp} |"
        )
    return lines


def tag_table(tag: str, truth: dict[int, dict], jobs: list[int]) -> list[str]:
    """Truth relevance tier x majority answer tier (soft score)."""
    res = lab.load_results(tag)
    grid = collections.Counter()
    for o in jobs:
        if o not in res:
            continue
        tiers = [a["relevance"] for a in map(answer, (r["judgment"] for r in res[o])) if a]
        top = collections.Counter(tiers).most_common(1)[0][0] if tiers else "failed"
        grid[truth[o]["relevance"], top] += 1
    cols = ["core", "involved", "uncertain", "hide", "failed"]
    out = [
        f"\n{tag}: truth (rows) vs majority answer (columns)\n",
        "| truth | " + " | ".join(cols) + " |",
        "|---" * (len(cols) + 1) + "|",
    ]
    for r in ["core", "involved", "uncertain", "hide"]:
        out.append(f"| {r} | " + " | ".join(str(grid[r, c]) for c in cols) + " |")
    return out


HEADER = (
    "| run | jobs | calls/job | failed calls | relevance missed (per call) | "
    "relevance extra (per call) | relevance missed / extra (vote) | "
    "shown missed (per call) | shown extra (per call) | shown missed / extra (vote) | "
    "seniority wrongly closed | seniority wrongly opened | jobs flipping |\n" + "|---" * 13 + "|"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--half", choices=("tune", "test", "both"), default="both")
    parser.add_argument("--show-test-jobs", action="store_true")
    parser.add_argument("tags", nargs="+")
    args = parser.parse_args()
    truth = {int(k): v for k, v in json.loads(TRUTH.read_text(encoding="utf-8")).items()}
    halves = ("tune", "test") if args.half == "both" else (args.half,)
    for half in halves:
        all_jobs = sorted(o for o, t in truth.items() if t["half"] == half)
        main_jobs = [o for o in all_jobs if truth[o]["source"] not in POLICY_SOURCES]
        policy_jobs = [o for o in all_jobs if truth[o]["source"] in POLICY_SOURCES]
        list_jobs = half == "tune" or args.show_test_jobs
        positives = sum(truth[o]["relevance"] != "hide" for o in main_jobs)
        visible = sum(shown(truth[o]) for o in main_jobs)
        print(
            f"\n## {half} half: {len(main_jobs)} jobs ({positives} relevant, {visible} "
            f"shown end to end){'' if list_jobs else ' -- sealed: counts only'}\n"
        )
        print(HEADER)
        for tag in args.tags:
            print("\n".join(score_tag(tag, truth, main_jobs, list_jobs)))
        print(
            f"\n### {half} half, the {len(policy_jobs)} review-changed jobs that wrote "
            "policy v1.2 (1.4.0 and v10 have seen their rules)\n"
        )
        print(HEADER)
        for tag in args.tags:
            print("\n".join(score_tag(tag, truth, policy_jobs, list_jobs)))
        if half == "tune":
            print(f"\n### Relevance tier, {half} half (soft score)")
            for tag in args.tags:
                print("\n".join(tag_table(tag, truth, main_jobs)))


if __name__ == "__main__":
    main()
