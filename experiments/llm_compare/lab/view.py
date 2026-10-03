"""Print cases for hand adjudication: both models' verdicts, then the full description.

  view.py rel 0 10      relevance disagreements, items 0..9
  view.py sen 0 10      seniority-only disagreements
  view.py ords 12,34    specific ordinals
"""

import json
import sys
from pathlib import Path

H = Path(__file__).resolve().parent
cases = {int(k): v for k, v in json.loads((H / "cases.json").read_text(encoding="utf-8")).items()}
disagree = json.loads((H / "sets.json").read_text())["disagree"]


def kind(o):
    lj, sj = cases[o]["luna0"].get("judgment"), cases[o]["sol0"].get("judgment")
    if not lj or not sj:
        return "failed"
    if lj["relevance"] != sj["relevance"]:
        return "rel"
    return "sen"


def show(o):
    c = cases[o]
    print(f"\n######## #{o} [{c['company']}] {c['title']}")
    for name in ("luna0", "sol0"):
        j = c[name].get("judgment")
        if not j:
            print(f"  {name}: {c[name]['disposition']} {c[name].get('errors')}")
            continue
        print(f"  {name}: rel={j['relevance']} sen={j['seniority_match']} ({j['required_experience']})")
        print(f"     rel_ev: {j['relevance_evidence'][:220]}")
        print(f"     rel_why: {j['relevance_reason'][:300]}")
        print(f"     sen_ev: {j['seniority_evidence'][:220]}")
        print(f"     sen_why: {j['seniority_reason'][:300]}")
    print("  --- description ---")
    print("  " + " ".join(c["description"].split()))


mode = sys.argv[1]
if mode == "ords":
    for o in sys.argv[2].split(","):
        show(int(o))
else:
    groups_path = H / "groups.json"
    groups = json.loads(groups_path.read_text()) if groups_path.exists() else {}
    selected = groups[mode] if mode in groups else [o for o in disagree if kind(o) == mode]
    start, count = int(sys.argv[2]), int(sys.argv[3])
    print(f"{mode}: {len(selected)} total, showing {start}..{start + count - 1}")
    for o in selected[start : start + count]:
        show(o)
