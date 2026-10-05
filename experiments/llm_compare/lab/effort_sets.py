"""The 500-job set for the prompt-v9 / reasoning-effort experiment (2026-10-04 batch).

  LAB_BATCH=2026-10-04 uv run --locked python experiments/llm_compare/lab/effort_sets.py

effort500 = every job in this batch with a user decision or a hand verdict (the 111
blind-judged Luna/Sol disagreements plus casebook-only jobs), filled to 500 with a seeded
random sample of jobs where Luna's and Sol's default-effort majorities agree. The agreed
jobs catch new errors a prompt or effort change might introduce on ordinary postings.
Deterministic: rerunning gives the same 500 jobs.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

SIZE = 500
rng = random.Random(20261005)
cases = lab.load_cases()
luna, sol = lab.load_results("luna13"), lab.load_results("sol13")


def majority_gate(results, o):
    gates = [r["judgment"]["relevance"] != "unrelated" for r in results.get(o, []) if r["judgment"]]
    return None if not gates else sum(gates) * 2 >= len(gates)


judged = {int(o) for o in json.loads((lab.HERE / "truth_2026-10-04.json").read_text("utf-8"))}
groups = json.loads((lab.HERE.parent / "casebook" / "groups_v0.json").read_text("utf-8"))
for group in groups["types"]:
    for ref in group["anchors"] + group["members"]:
        batch, ordinal = ref.split(":")
        if batch == "10-04":
            judged.add(int(ordinal))
agreed = sorted(
    o
    for o in cases
    if o not in judged
    and majority_gate(luna, o) is not None
    and majority_gate(luna, o) == majority_gate(sol, o)
)
fill = rng.sample(agreed, SIZE - len(judged))

sets = json.loads(lab.SETS.read_text(encoding="utf-8"))
sets["effort500"] = sorted(judged | set(fill))
lab.SETS.write_text(json.dumps(sets))
print(
    f"effort500: {len(sets['effort500'])} jobs ({len(judged)} with a decision or verdict, "
    f"{len(fill)} agreed; {sum(majority_gate(sol, o) for o in fill)} of the agreed are relevant)"
)
