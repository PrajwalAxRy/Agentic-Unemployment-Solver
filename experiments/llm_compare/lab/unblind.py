"""Turn blind verdicts into a truth file, then reveal who was right on each disagreement.

  LAB_BATCH=2026-10-04 python unblind.py blind_verdicts_2026-10-04.txt luna13 sol13

Writes truth_<batch>.json (relevance + conf + note; seniority is left to the reference).
"""

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

LABEL = {"s": "substantive", "p": "peripheral", "u": "unrelated"}
verdicts = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    head, note = line.split("|", 1)
    ordinal, relevance, conf = head.split()
    verdicts[int(ordinal)] = {"relevance": LABEL[relevance], "conf": conf, "note": note.strip()}
out = lab.HERE / f"truth_{lab.BATCH_NAME}.json"
out.write_text(json.dumps(verdicts, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {len(verdicts)} verdicts to {out.name}")

luna, sol = lab.load_results(sys.argv[2]), lab.load_results(sys.argv[3])
side = json.loads((lab.HERE / f"disagreements_{lab.BATCH_NAME}.json").read_text())
cases = lab.load_cases()


def gates(results, o):
    return [r["judgment"]["relevance"] != "unrelated" for r in results.get(o, []) if r["judgment"]]


tally = collections.Counter()
for name, ordinals in side.items():
    for o in ordinals:
        v = verdicts[o]
        truth = v["relevance"] != "unrelated"
        lg, sg = gates(luna, o), gates(sol, o)
        luna_pass = sum(lg) * 2 >= len(lg)
        winner = "luna" if luna_pass == truth else "sol"
        tally[(name, v["conf"] != "low", winner)] += 1
        print(
            f"{name:9s} {o:5d} truth={v['relevance'][:4]} {v['conf']:4s} "
            f"luna={''.join('p' if g else 'u' for g in lg)} "
            f"sol={''.join('p' if g else 'u' for g in sg)}"
            f" right={winner:4s} [{cases[o]['company']}] {cases[o]['title'][:45]}"
        )
print()
for name in side:
    for confident in (True, False):
        label = "med/high" if confident else "low"
        print(
            f"{name:9s} {label:8s} luna right {tally[(name, confident, 'luna')]:3d}  "
            f"sol right {tally[(name, confident, 'sol')]:3d}"
        )
