"""Append hand verdicts to truth.json.

Usage: adjudicate.py '<ordinal> <relevance|=luna|=sol> <seniority|=agreed|=luna|=sol> <conf> <note>' ...
  relevance: substantive|peripheral|unrelated, or =luna / =sol to copy that model
  seniority: True|False|uncertain, =agreed (both models agreed), =luna, =sol
  conf: high|med|low  (low = genuinely borderline; excluded from tuning targets)
"""

import json
import sys
from pathlib import Path

H = Path(__file__).resolve().parent
cases = {int(k): v for k, v in json.loads((H / "cases.json").read_text(encoding="utf-8")).items()}
path = H / "truth.json"
truth = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def pick(o, value, field):
    if value.startswith("="):
        source = value[1:]
        if source == "agreed":
            a = cases[o]["luna0"]["judgment"][field]
            b = cases[o]["sol0"]["judgment"][field]
            assert a == b, f"#{o} {field} not agreed: {a} vs {b}"
            return a
        return cases[o][source + "0"]["judgment"][field]
    if field == "seniority_match" and value in ("True", "False"):
        return value == "True"
    return value


for spec in sys.argv[1:]:
    o, rel, sen, conf, note = spec.split(" ", 4)
    o = int(o)
    truth[str(o)] = {
        "relevance": pick(o, rel, "relevance"),
        "seniority_match": pick(o, sen, "seniority_match"),
        "conf": conf,
        "note": note,
    }
path.write_text(json.dumps(truth, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"{len(truth)} verdicts")
