"""Compare ways of turning several model calls into one verdict, using recorded reruns.

Every strategy is simulated from calls already made (3 Luna reruns per job, Sol reruns),
so no new requests are needed. Only the relevance gate is scored ("does the job pass
'not unrelated'"), since that decides whether a job reaches the report.

  uv run --locked python experiments/llm_compare/lab/strategies.py
"""

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

LUNA_CALL = 0.00030  # $/job, measured for prompt 1.2.0
SOL_CALL = 0.0036

cases = lab.load_cases()
sets = json.loads(lab.SETS.read_text())
truth = {int(k): v for k, v in json.loads((lab.HERE / "truth.json").read_text("utf-8")).items()}


def reference(o: int):
    """Hand verdict (medium/high confidence), else the two models' original consensus."""
    t = truth.get(o)
    if t:
        return None if t["conf"] == "low" else t["relevance"] != "unrelated"
    luna, sol = cases[o]["luna0"].get("judgment"), cases[o]["sol0"].get("judgment")
    if luna and sol and luna["relevance"] == sol["relevance"]:
        return sol["relevance"] != "unrelated"
    return None


def gate(record) -> bool | None:
    j = record["judgment"]
    return None if j is None else j["relevance"] != "unrelated"


def calls(tag: str) -> dict[int, list]:
    return {o: [gate(r) for r in rs] for o, rs in lab.load_results(tag).items()}


def evaluate(name, verdicts_by_job, cost):
    """verdicts_by_job: {ordinal: [possible outcomes, equally likely]}."""
    missed = extra = n = 0.0
    for o, outcomes in verdicts_by_job.items():
        ref = reference(o)
        if ref is None or not outcomes:
            continue
        n += 1
        missed += sum(ref and not v for v in outcomes) / len(outcomes)
        extra += sum(v and not ref for v in outcomes) / len(outcomes)
    print(f"  {name:38s} missed {missed:5.1f}  extra {extra:5.1f}  of {int(n)}   ${cost:.5f}/job")


def run(set_name: str, luna_tag: str, sol_tag: str | None):
    luna = calls(luna_tag)
    sol = calls(sol_tag) if sol_tag else {}
    jobs = [o for o in sets[set_name] if o in luna and len(luna[o]) >= 3]
    print(f"\n== {set_name} ({luna_tag} x3{', ' + sol_tag if sol_tag else ''})")

    def show(v):  # a failed call (None) shows nothing
        return bool(v)

    evaluate("1 Luna call (production today)",
             {o: [show(v) for v in luna[o]] for o in jobs}, LUNA_CALL)
    evaluate("majority of 3 Luna calls",
             {o: [sum(map(show, luna[o][:3])) >= 2] for o in jobs}, 3 * LUNA_CALL)

    # 2 calls; a third only when they disagree on the gate (= majority of 3, cheaper).
    tie_rate = sum(show(luna[o][0]) != show(luna[o][1]) for o in jobs) / len(jobs)
    evaluate("2 Luna, 3rd Luna only if they disagree",
             {o: [sum(map(show, luna[o][:3])) >= 2] for o in jobs},
             (2 + tie_rate) * LUNA_CALL)

    # Show the job if either of two calls says relevant (misses cost more than extras).
    evaluate("2 Luna, show if either says relevant",
             {o: [show(a) or show(b) for a, b in itertools.combinations(luna[o][:3], 2)]
              for o in jobs}, 2 * LUNA_CALL)

    if sol:
        sol_jobs = [o for o in jobs if sol.get(o)]
        evaluate("2 Luna, Sol breaks a tie",
                 {o: [show(a) if show(a) == show(b) else show(sol[o][0])
                      for a, b in itertools.combinations(luna[o][:3], 2)] for o in sol_jobs},
                 2 * LUNA_CALL + tie_rate * SOL_CALL)
        evaluate("1 Sol call (new prompt)",
                 {o: [show(v) for v in sol[o]] for o in sol_jobs}, SOL_CALL)
        print(f"  (Luna's first two calls disagree on {tie_rate:.1%} of these jobs)")


run("disagree", "luna_v4", "sol_v4")
run("holdout", "luna_v4h", "sol_v4h")
run("agree", "luna_v4", None)
