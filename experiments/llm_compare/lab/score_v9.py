"""Score runs on effort500 against the user's decisions, hand verdicts and agreement.

  LAB_BATCH=2026-10-04 python score_v9.py luna13 sol13 v9_luna_default v9_luna_high ...

Labels (show / uncertain / hide), in order of authority:
1. the user's casebook decision for the job's type, or their job-level override, with the
   later clarification that a role only sitting in an AI organisation is "uncertain";
2. a hand verdict (medium/high confidence): substantive or peripheral = show, unrelated = hide;
3. otherwise the default-effort Luna and Sol majorities, which agree on these jobs.

Model answers: prompt 1.x substantive/peripheral = show, unrelated = hide; prompt 2.x
core_ai/ai_involved = show, uncertain = uncertain (displayed with a tag), not_ai = hide.
A label of "uncertain" is met by a shown or uncertain answer; only "hide" misses it.
Every call counts (no voting) unless a table says "majority".
"""

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

LEVEL = {
    "substantive": "show",
    "peripheral": "show",
    "unrelated": "hide",
    "core_ai": "show",
    "ai_involved": "show",
    "uncertain": "uncertain",
    "not_ai": "hide",
}
SHOWN = {"show", "uncertain"}
# Jobs that a worked example in prompt v9 paraphrases: reported separately, because the
# prompt has effectively seen their answer.
EXAMPLE_SOURCES = {
    671,
    796,
    1889,
    300,
    185,
    180,
    217,
    307,
    1474,
    1475,
    2728,
    941,
    889,
    7,
    345,
    1622,
    2017,
    2536,
    2569,
    1137,
    281,
    1675,
    1786,
    1598,
    437,
    614,
    663,
    1538,
    3130,
    3158,
    499,
}
# The user's later rule: a team that builds AI is shown; a role that only sits in an AI
# organisation is uncertain. These two overrides predate the rule.
CLARIFIED = {315: "uncertain", 300: "uncertain"}

tags = sys.argv[1:]
ordinals = lab.load_set("effort500")
casebook = json.loads((lab.HERE.parent / "casebook" / "decisions_v0.json").read_text("utf-8"))
groups = json.loads((lab.HERE.parent / "casebook" / "groups_v0.json").read_text("utf-8"))
verdicts = {
    int(k): v
    for k, v in json.loads((lab.HERE / "truth_2026-10-04.json").read_text("utf-8")).items()
}

labels, source = {}, {}
for group in groups["types"]:
    decision = casebook["types"][group["key"]]["decision"]
    for ref in group["anchors"] + group["members"]:
        batch, ordinal = ref.split(":")
        if batch != "10-04":
            continue
        override = (casebook["jobs"].get(ref) or {}).get("override")
        labels[int(ordinal)] = CLARIFIED.get(int(ordinal), override or decision)
        source[int(ordinal)] = "user decision"
for o, v in verdicts.items():
    if o not in labels and v["conf"] != "low":
        labels[o] = "hide" if v["relevance"] == "unrelated" else "show"
        source[o] = "hand verdict"
luna0, sol0 = lab.load_results("luna13"), lab.load_results("sol13")
for o in ordinals:
    if o not in labels:
        gates = [
            r["judgment"]["relevance"] != "unrelated"
            for r in luna0.get(o, []) + sol0.get(o, [])
            if r["judgment"]
        ]
        if gates:
            labels[o] = "show" if sum(gates) * 2 >= len(gates) else "hide"
            source[o] = "agreed"

print(
    f"jobs: {len(ordinals)}; labels by source: {dict(collections.Counter(source.values()))}; "
    f"labels: {dict(collections.Counter(labels[o] for o in ordinals if o in labels))}\n"
)


def calls_for(res, o):
    return [r for r in res.get(o, []) if r["judgment"]]


def level(record):
    return LEVEL[record["judgment"]["relevance"]]


results = {tag: lab.load_results(tag) for tag in tags}
row = "| {:24s} | {:>6s} | {:>7s} | {:>7s} | {:>9s} | {:>9s} | {:>8s} | {:>9s} |"
print("## Gate errors per call (a miss = a job you want shown, answered hide)\n")
print(row.format("run", "calls", "missed", "extra", "maj miss", "maj extra", "unstable", "failed"))
print(row.format(*["---"] * 8))
for tag in tags:
    res = results[tag]
    missed = extra = maj_missed = maj_extra = unstable = n_calls = failed = 0
    for o in ordinals:
        if o not in labels:
            continue
        failed += sum(1 for r in res.get(o, []) if not r["judgment"])
        calls = calls_for(res, o)
        if not calls:
            continue
        n_calls += len(calls)
        want = labels[o] in SHOWN
        shown = [level(r) in SHOWN for r in calls]
        missed += sum(want and not s for s in shown) / len(calls)
        extra += sum(s and not want for s in shown) / len(calls)
        majority = sum(shown) * 2 >= len(shown)
        maj_missed += want and not majority
        maj_extra += majority and not want
        unstable += len(set(shown)) > 1
    print(
        row.format(
            tag,
            str(n_calls),
            f"{missed:.1f}",
            f"{extra:.1f}",
            str(maj_missed),
            str(maj_extra),
            str(unstable),
            str(failed),
        )
    )

print("\n## The same, split by where the label comes from (per call: missed / extra)\n")
strata = ["user decision", "hand verdict", "agreed"]
print(
    "| run | "
    + " | ".join(f"{s} ({sum(source.get(o) == s for o in ordinals)})" for s in strata)
    + " | prompt examples | other |"
)
print("|---" * (len(strata) + 3) + "|")
for tag in tags:
    res, cells = results[tag], []
    for subset in [[o for o in ordinals if source.get(o) == s] for s in strata] + [
        [o for o in ordinals if o in EXAMPLE_SOURCES and o in labels],
        [o for o in ordinals if o not in EXAMPLE_SOURCES and o in labels],
    ]:
        m = e = 0.0
        for o in subset:
            calls = calls_for(res, o)
            if calls:
                want = labels[o] in SHOWN
                m += sum(want and level(r) not in SHOWN for r in calls) / len(calls)
                e += sum(level(r) in SHOWN and not want for r in calls) / len(calls)
        cells.append(f"{m:.1f} / {e:.1f}")
    print(f"| {tag} | " + " | ".join(cells) + " |")

print(
    "\n## Show vs uncertain: your label (rows) against the model's answer (columns), "
    "calls averaged per job\n"
)
for tag in tags:
    res = results[tag]
    table = collections.defaultdict(float)
    for o in ordinals:
        calls = calls_for(res, o)
        if o in labels and calls:
            for r in calls:
                table[(labels[o], level(r))] += 1 / len(calls)
    print(
        f"**{tag}**\n\n| your label | model show | model uncertain | model hide |\n"
        "|---|---|---|---|"
    )
    for want in ("show", "uncertain", "hide"):
        print(
            f"| {want} ({sum(labels.get(o) == want for o in ordinals)}) | "
            + " | ".join(f"{table[(want, got)]:.1f}" for got in ("show", "uncertain", "hide"))
            + " |"
        )
    print()

print(
    "## What would reach the report "
    "(majority over calls; relevance shown and seniority not false)\n"
)
print(
    "| run | shown | of which relevance uncertain | seniority true | "
    "seniority uncertain | seniority false |"
)
print("|---|---|---|---|---|---|")
for tag in tags:
    res = results[tag]
    counts = collections.Counter()
    for o in ordinals:
        calls = calls_for(res, o)
        if not calls:
            continue
        levels = collections.Counter(level(r) for r in calls)
        rel = (
            "uncertain"
            if levels["uncertain"] * 2 >= len(calls)
            else ("show" if levels["show"] + levels["uncertain"] > levels["hide"] else "hide")
        )
        sen = collections.Counter(str(r["judgment"]["seniority_match"]) for r in calls).most_common(
            1
        )[0][0]
        counts[f"sen_{sen}"] += 1
        if rel in SHOWN and sen != "False":
            counts["shown"] += 1
            counts["shown_uncertain"] += rel == "uncertain"
    print(
        f"| {tag} | {counts['shown']} | {counts['shown_uncertain']} | {counts['sen_True']} | "
        f"{counts['sen_uncertain']} | {counts['sen_False']} |"
    )
