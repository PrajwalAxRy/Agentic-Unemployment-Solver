"""Gate and visibility flips against a two-model consensus (Luna v4 + Sol v4 agree).

  LAB_BATCH=2026-10-03 python score_consensus.py luna_v4_c,luna_v8 consensus300

Every call counts (no voting), so the numbers are the expected per-call flip rate.
Flips are not automatically errors -- the consensus can be wrong -- so each is listed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

luna, sol = lab.load_results("luna_v4"), lab.load_results("sol_v4")
cases = lab.load_cases()
ordinals = lab.load_set(sys.argv[2])


def first(results, o):
    return next((r["judgment"] for r in results.get(o, []) if r["judgment"]), None)


for tag in sys.argv[1].split(","):
    res = lab.load_results(tag)
    lost = gained = shown = hidden = calls = 0
    flips = []
    for o in ordinals:
        ref = first(luna, o)
        if ref is None or o not in res:
            continue
        ref_gate = ref["relevance"] != "unrelated"
        ref_seen = lab.visible(ref["relevance"], str(ref["seniority_match"]))
        for r in res[o]:
            calls += 1
            j = r["judgment"]
            gate = bool(j) and j["relevance"] != "unrelated"
            seen = bool(j) and lab.visible(j["relevance"], str(j["seniority_match"]))
            lost += ref_gate and not gate
            gained += gate and not ref_gate
            hidden += ref_seen and not seen
            shown += seen and not ref_seen
            if gate != ref_gate:
                flips.append(f"{o}{'-' if ref_gate else '+'}")
    print(
        f"{tag:10s} calls={calls} gate lost={lost} gained={gained} | "
        f"visible lost={hidden} gained={shown} | {' '.join(flips)}"
    )
