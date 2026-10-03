"""Luna vs Sol agreement on one comparison folder (read-only)."""
import collections as C, json, sqlite3, sys
D = sys.argv[1]
def load(m):
    c = sqlite3.connect(f"file:{D}/{m}/jobs.sqlite3?mode=ro", uri=True)
    return {o: (json.loads(p), json.loads(r)) for o, p, r in
            c.execute("select ordinal, payload_json, result_json from batch_candidates")}
L, S = load("luna"), load("sol")
disp = C.Counter((L[o][1]["disposition"], S[o][1]["disposition"]) for o in L)
print("disposition (luna, sol):", dict(disp))
both = [o for o in L if L[o][1]["disposition"] == S[o][1]["disposition"] == "completed"]
print("both completed:", len(both))
F = ("relevance", "seniority_match", "location_eligible")
for f in F:
    pairs = [(L[o][1]["judgment"][f], S[o][1]["judgment"][f]) for o in both]
    pairs = [p for p in pairs if p != (None, None)]
    dis = C.Counter((str(a), str(b)) for a, b in pairs if a != b)
    print(f"\n{f}: asked {len(pairs)}, disagree {sum(dis.values())} ({100*sum(dis.values())/max(1,len(pairs)):.1f}%)")
    for (a, b), n in dis.most_common(): print(f"   luna={a:12s} sol={b:12s} {n}")
    agree = C.Counter(str(a) for a, b in pairs if a == b)
    print("   agreed distribution:", dict(agree))
# Outcome-level: does the job end up in the report differently?
def outcome(j):
    if j["relevance"] == "unrelated": return "rejected:relevance"
    if j.get("location_eligible") is False: return "rejected:location"
    if j.get("location_eligible") == "uncertain": return "review:location"
    s = j["seniority_match"]
    return "match" if s is True else "rejected:seniority" if s is False else "review:seniority"
oc = C.Counter((outcome(L[o][1]["judgment"]), outcome(S[o][1]["judgment"])) for o in both)
diff = {k: v for k, v in oc.items() if k[0] != k[1]}
print(f"\nfinal outcome differs on {sum(diff.values())}/{len(both)} jobs ({100*sum(diff.values())/len(both):.1f}%)")
for (a, b), n in sorted(diff.items(), key=lambda x: -x[1]): print(f"   luna={a:20s} sol={b:20s} {n}")
print("\nmatches: luna", sum(v for (a, _), v in oc.items() if a == "match"), "sol", sum(v for (_, b), v in oc.items() if b == "match"))
by_co = C.Counter(L[o][0]["company_id"] for o in both if outcome(L[o][1]["judgment"]) != outcome(S[o][1]["judgment"]))
print("outcome disagreements by company (top 10):", by_co.most_common(10))
