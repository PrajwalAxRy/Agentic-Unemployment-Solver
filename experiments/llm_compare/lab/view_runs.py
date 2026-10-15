"""Print cases with the answers from harness runs (any batch), then the full description.

LAB_BATCH=2026-10-03 python view_runs.py luna_v4,sol_v4 12,34,56
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

tags = sys.argv[1].split(",")
ordinals = [int(o) for o in sys.argv[2].split(",")]
cases = lab.load_cases()
results = {tag: lab.load_results(tag) for tag in tags}
for o in ordinals:
    c = cases[o]
    print(f"\n######## #{o} [{c['company']}] {c['title']} | location: {c['location_original']}")
    for tag in tags:
        for r in results[tag].get(o, []):
            j = r["judgment"]
            if not j:
                print(f"  {tag}: {r['disposition']}")
                continue
            print(f"  {tag}: rel={j['relevance']} sen={j['seniority_match']}")
            print(f"     rel_ev: {j['relevance_evidence'][:200]}")
            print(f"     rel_why: {j['relevance_reason'][:260]}")
            break  # first valid answer is enough for adjudication
    print("  --- description ---\n  " + " ".join(c["description"].split()))
