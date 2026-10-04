"""Luna reruns vs a Sol majority on one batch: strategies, disagreements, and a todo list.

  LAB_BATCH=2026-10-04 python analyze_reps.py luna13 sol13 [--truth truth_2026-10-04.json]

The reference is Sol's majority over its reruns, unless a hand verdict exists (any
confidence except "low"), which then wins. Every Luna strategy is simulated from Luna's
recorded reruns, averaged over every order of those reruns, so no new calls are needed.
"Gate" = relevance is not "unrelated". "Shown" = gate passes and seniority is not false.
Writes disagreements_<batch>.json: the jobs where Luna's and Sol's majorities differ.
"""

import argparse
import collections
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("luna")
p.add_argument("sol")
p.add_argument("--truth")
p.add_argument("--only-judged", action="store_true",
               help="score only hand-judged jobs, so neither model is its own reference")
args = p.parse_args()

cases = lab.load_cases()
luna, sol = lab.load_results(args.luna), lab.load_results(args.sol)
truth = {}
if args.truth:
    truth = {int(k): v for k, v in json.loads(Path(args.truth).read_text("utf-8")).items()
             if v.get("conf") != "low"}


def answers(results, o):
    """(gate, seniority) per valid call; failed calls are dropped."""
    return [(r["judgment"]["relevance"] != "unrelated", str(r["judgment"]["seniority_match"]))
            for r in results.get(o, []) if r["judgment"]]


def majority(values, tie):
    counts = collections.Counter(values)
    best = max(counts.values())
    top = [v for v, n in counts.items() if n == best]
    return top[0] if len(top) == 1 else tie


ref, luna_calls = {}, {}
for o in cases:
    s, lu = answers(sol, o), answers(luna, o)
    if not s or len(lu) < 3 or (args.only_judged and o not in truth):
        continue
    gate = majority([g for g, _ in s], tie=True)
    sen = majority([x for _, x in s], tie="uncertain")
    if o in truth:
        gate = truth[o]["relevance"] != "unrelated"
        sen = str(truth[o].get("seniority_match", sen))
    ref[o] = (gate, sen)
    luna_calls[o] = lu


def shown(gate, sen):
    return gate and sen != "False"


def strategy(pick):
    """pick(list of (gate, sen) in one order) -> (gate, sen). Averaged over orders."""
    missed = extra = smissed = sextra = 0.0
    for o, calls in luna_calls.items():
        orders = list(itertools.permutations(calls))
        for order in orders:
            gate, sen = pick(list(order))
            rg, rs = ref[o]
            w = 1 / len(orders)
            missed += w * (rg and not gate)
            extra += w * (gate and not rg)
            smissed += w * (shown(rg, rs) and not shown(gate, sen))
            sextra += w * (shown(gate, sen) and not shown(rg, rs))
    return missed, extra, smissed, sextra


def one(order):
    return order[0]


def second_opinion(order):
    """Production rule: 2 calls; a 3rd on a gate disagreement; majority; tie -> pass."""
    a, b = order[0], order[1]
    if a[0] == b[0] or len(order) < 3:
        return a
    c = order[2]
    return a if a[0] == c[0] else b


def either(order):
    a, b = order[0], order[1]
    return (a[0] or b[0], a[1] if a[0] else b[1])


def majority3(order):
    gate = sum(g for g, _ in order[:3]) >= 2
    sen = majority([x for _, x in order[:3]], tie="uncertain")
    return gate, sen


print(f"jobs scored: {len(ref)} (reference: Sol majority over its reruns"
      f"{', overridden by ' + str(len(truth)) + ' hand verdicts' if truth else ''})")
print(f"reference gate passes: {sum(g for g, _ in ref.values())}, "
      f"shown: {sum(shown(*v) for v in ref.values())}")
print(f"{'strategy':36s} {'gate missed':>11s} {'gate extra':>10s} "
      f"{'shown missed':>12s} {'shown extra':>11s}")
for name, pick in (("1 Luna call", one), ("2 Luna + tie-break (second opinion)",
                   second_opinion), ("2 Luna, show if either passes", either),
                   ("majority of 3 Luna", majority3)):
    m, e, sm, se = strategy(pick)
    print(f"{name:36s} {m:11.1f} {e:10.1f} {sm:12.1f} {se:11.1f}")

# One Sol call against the reference. Without hand verdicts this is Sol's own noise; with
# them it is Sol's per-call error, but only the hand-judged jobs can count against Sol.
sol_missed = sum(
    sum(ref[o][0] and not g for g, _ in answers(sol, o)) / len(answers(sol, o)) for o in ref
)
sol_extra = sum(
    sum(g and not ref[o][0] for g, _ in answers(sol, o)) / len(answers(sol, o)) for o in ref
)
print(f"{'1 Sol call':36s} {sol_missed:11.1f} {sol_extra:10.1f}"
      f"   (vs {'reference' if truth else 'its own majority: noise only'})")

unstable = {o for o, calls in luna_calls.items() if len({g for g, _ in calls}) > 1}
print(f"Luna gate unstable across its reruns: {len(unstable)} jobs; "
      f"Sol: {sum(len({g for g, _ in answers(sol, o)}) > 1 for o in ref)}")

# Where the majorities disagree on the gate (ties count as pass, as in production).
disagree = {"luna_only": [], "sol_only": []}
for o, calls in luna_calls.items():
    lg = sum(g for g, _ in calls) * 2 >= len(calls)
    if lg and not ref[o][0]:
        disagree["luna_only"].append(o)
    elif ref[o][0] and not lg:
        disagree["sol_only"].append(o)
print(f"majority gate disagreements: Luna-only pass {len(disagree['luna_only'])}, "
      f"Sol-only pass {len(disagree['sol_only'])}")
if not truth:  # the blind-review todo list is defined against the models alone
    out = lab.HERE / f"disagreements_{lab.BATCH_NAME}.json"
    out.write_text(json.dumps(disagree))
    print(f"wrote {out.name}")
