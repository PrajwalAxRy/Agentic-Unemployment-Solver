"""Validation sets for the 2026-10-03 batch, untouched while tuning prompts v5-v8.

  LAB_BATCH=2026-10-03 uv run --locked python experiments/llm_compare/lab/fresh_validation_sets.py

- `unadjudicated`: gate disagreements (Luna v4 vs Sol v4) that were not hand-judged while
  tuning; a blind sample of these is adjudicated afterwards.
- `consensus300`: random jobs where Luna v4 and Sol v4 agree on the gate. Their shared
  answer is the reference; it measures what a prompt change breaks on ordinary postings.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

todo = json.loads((lab.HERE / "fresh_todo.json").read_text(encoding="utf-8"))
tuned = {int(o) for o in json.loads((lab.HERE / "truth_2026-10-03.json").read_text("utf-8"))}
disagreements = set(todo["luna_only"]) | set(todo["sol_only"])
luna, sol = lab.load_results("luna_v4"), lab.load_results("sol_v4")


def gate(results, o):
    for record in results.get(o, []):
        if record["judgment"]:
            return record["judgment"]["relevance"] != "unrelated"
    return None


agreeing = sorted(
    o for o in lab.load_cases()
    if o not in disagreements and gate(luna, o) is not None and gate(luna, o) == gate(sol, o)
)
sets = json.loads(lab.SETS.read_text(encoding="utf-8"))
sets["unadjudicated"] = sorted(disagreements - tuned)
sets["consensus300"] = sorted(random.Random(20261004).sample(agreeing, 300))
lab.SETS.write_text(json.dumps(sets))
print({name: len(sets[name]) for name in ("unadjudicated", "consensus300")},
      "relevant in consensus300:", sum(gate(luna, o) for o in sets["consensus300"]))
