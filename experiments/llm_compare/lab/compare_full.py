"""Whole-batch effect of a prompt change: relevant / shown counts and flips per tag.

  LAB_BATCH=2026-10-03 python compare_full.py luna_v4,luna_v8_all,sol_v4

The first tag is the baseline for flips. "Shown" = relevant and seniority not false
(a match or a review row); location is ignored here.
"""

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

tags = sys.argv[1].split(",")
cases = lab.load_cases()
res = {t: lab.load_results(t) for t in tags}


def first(t, o):
    return next((r["judgment"] for r in res[t].get(o, []) if r["judgment"]), None)


base = tags[0]
for t in tags:
    rel = shown = failed = 0
    lost, gained = [], []
    for o in cases:
        j = first(t, o)
        if j is None:
            failed += 1
            continue
        rel += j["relevance"] != "unrelated"
        seen = lab.visible(j["relevance"], str(j["seniority_match"]))
        shown += seen
        b = first(base, o)
        if t != base and b is not None:
            b_seen = lab.visible(b["relevance"], str(b["seniority_match"]))
            if b_seen and not seen:
                lost.append(o)
            elif seen and not b_seen:
                gained.append(o)
    print(f"{t:12s} relevant={rel} shown={shown} failed={failed}"
          + (f" | shown vs {base}: lost {len(lost)} gained {len(gained)}" if t != base else ""))
    if t != base:
        for name, group in (("lost", lost), ("gained", gained)):
            by = collections.Counter(cases[o]["company"] for o in group)
            print(f"   {name} by company: {dict(by.most_common(8))}")
            print(f"   {name}: {','.join(map(str, group))}")
