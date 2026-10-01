# Decision log

Every decision that closed off an alternative, with the reasoning and the evidence behind
it. **A conclusion without its reasoning gets re-litigated** — that is what this file
prevents.

**If you are about to propose an optimisation or a design change, read this first.**
Several obvious-looking improvements here were evaluated with real numbers and rejected.
Re-proposing them costs tokens and, in one case, would actively break the system.

**Adding an entry:** date it, state what was decided, give the reason, and — where one
exists — the measurement. Mark it `SETTLED`, `DEFERRED`, or `SUPERSEDED`. Superseded
entries stay, with a pointer; deleting them loses the reason the change was made.

---

## D1. Title filter is deliberately generous — do not tighten it
**2026-09-30 · SETTLED · `to_change.md` 2.2a**

The title filter passes ~70–79% of titles, not the ~11% it once did. `filter_role` returns
`CONDITIONAL_DESCRIPTION` for every survivor; `EXPLICIT_PASS` exists in the enum but is
unreachable, so **nothing skips the LLM gate**.

**Why:** the old narrow filter silently dropped real jobs. `Machine Learning Engineer,
Prime Video Ads CX` was blocked on `"pr"` inside *Prime*. `Software Development Engineer
II, Enterprise Engineering` reached the final report in a real scan and the proposed filter
would have dropped it. Word boundaries fix substring bugs but not domain-versus-function
confusion, so the rule became: if a title contains an engineering function word, the
blocklist is not consulted at all.

**Evidence:** validated against 1,300 live Amazon India titles, 1,120 Greenhouse titles
across 14 companies, 77 hand-written cases, and all 130 titles that passed the old filter.
**0 false negatives, 0 regressions.** Two adversarial passes (~700 constructed titles)
found 8 bug classes, all fixed.

**Consequence to expect:** `conditional_pass` runs ~94% of retained rows. That is the
design, not a leak. Tightening the title filter to cut LLM volume re-introduces exactly the
false negatives this was built to eliminate. If report volume is the complaint, tier the
output on `substantive` vs `peripheral` instead.

---

## D2. Send full descriptions to the LLM — no trimming
**2026-09-30 · SETTLED · user decision**

Descriptions go to the model untruncated, averaging ~23,000 characters (~5,742 tokens).

**Why:** trimming to 4,000 characters saves about **$4 per full scan** — real, but small
against the risk. Seniority signal is often back-loaded ("reporting to the Director of ML",
"8+ years required" in a late requirements block). Worse, the merged prompt validates that
quoted evidence appears **verbatim in the text that was sent**; trimming away a quotable
sentence causes a validation failure and triggers the retry, so aggressive trimming can
*increase* call volume while degrading accuracy.

**Evidence:** at $0.0020/job a full 3,677-job scan is $7.23. Trimming saves ~$3.85 of that.

**If revisited:** the honest method is to run the same jobs trimmed and untrimmed, compare
against the evaluation set, and ship only a cap that changes no verdicts.

---

## D3. Prompt caching preferred over trimming
**2026-09-30 · DEFERRED**

The 5,331-character system prompt is byte-identical on every call and sits at the start of
the payload, so it is cacheable at a tenth of the input rate. Saves ~$1/scan with **zero
accuracy risk**, which is why it is preferred to trimming despite saving less.

**Unverified:** whether the AMD gateway passes cache breakpoints through to the provider.
Check before relying on it. If it does not, the loss is ~$1/scan — not worth further work.

---

## D4. Per-run token caps sized at 1.6× measured need
**2026-09-30 · SETTLED**

```
JOB_FINDER_LLM_MAX_REQUESTS=7000                    # need 4,045
JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS=47000000  # need 28.9M
JOB_FINDER_LLM_MAX_OUTPUT_TOKENS=2000000            # need 1.21M
```

**Why:** the previous 1M-token cap was exhausted 140 jobs into a 3,677-job run. It
protected roughly **$1.40** and cost the scan its entire output. Headroom exists because
the retained set varies day to day; a cap that trips on a slightly larger day is a cap set
wrong.

These are **per-run**, not cumulative — `UsageBudget` is rebuilt on each invocation.
Expected full scan ~$7.23; worst case if every cap is hit, ~$12.52.

---

## D5. Budget exhaustion is not a per-job failure
**2026-09-30 · SETTLED · commit `df0c60d`**

`EvaluationDisposition.BUDGET_EXHAUSTED` is distinct from `MANUAL_REVIEW`. The record stays
**pending**; `fail_evaluation()` is not called. The phase halts on the first exhaustion
rather than walking the remaining rows.

**Why:** budget exhaustion previously wrote `reason_code=invalid_seniority_output` — a
claim that the model judged the job and returned something unusable, when no request was
ever sent. Because `_needs_processing` only retried a narrow set of reason codes, **3,026
rows became permanently unreachable**. Only a prompt or model version bump would have
recovered them, which also invalidates the entire cache.

**General rule, beyond this bug:** never record a transient or environmental condition as
durable per-job state. If a status means "we did not get to it", it must be distinguishable
from "we judged it and it failed".

---

## D6. Resume uses a checkpoint file, not a re-scan
**2026-09-30 · SETTLED · commits `0fe8d3e`, checkpoint module**

On a budget halt, the unevaluated rows are written to `state/resume_checkpoint.json`.
`scan --resume` skips collection and filtering entirely.

**Why:** a scan spends ~3.5h scraping before the first LLM call. Re-running from the top
pays that again to rebuild a list the halted run already had.

**Guards, each deliberate:** refused after **24h** (postings close, and resuming onto stale
data spends budget on rows the next scan would retire); refused if `profile_version`,
`prompt_version` or `model_policy` changed (one report must not merge verdicts judged under
different rules); a corrupt checkpoint is an error, never a silent fallback to a four-hour
full scan.

**Lifecycle is skipped on resume.** Absence detection needs the complete listing set; a
checkpoint holds a slice, so running it would mark live jobs as missing and retire them.

**Descriptions are stored in the checkpoint** despite the size cost. Dropping them looked
like a cheap saving, but roughly a third of listings carry the description inline —
omitting it forces an HTTP request the original run never needed, which can fail and send
the row to review instead of the model.

---

## D7. Token prices live in `.env`, never in code
**2026-09-30 · SETTLED**

`JOB_FINDER_LLM_{INPUT,OUTPUT}_COST_PER_MTOK`. Unset rates report cost as **unknown**, not
zero.

**Why:** model prices move — the tier this project uses fell 80% in a single month during
2026 — and a gateway or reseller may not bill list price at all. A hardcoded table goes
stale silently and produces confidently wrong money. A free run and an unpriceable run must
not look identical, and both rates are required together because pricing input but not
output would under-report every run while still looking authoritative.

---

## D8. Schema bounds, injection hardening and retry rework — deferred
**2026-09-30 · DEFERRED**

Three real defects in the merged LLM call, all consciously **not** fixed:

1. The merged schema dropped every `maxLength` that `seniority.py:62-68` still has.
   Unbounded strings reach SQLite and markdown reports.
2. Evidence validation is a substring check with no minimum length — `"a"` and `""` both
   pass as "verbatim excerpts".
3. The retry resends a byte-identical request with no error feedback, and no
   `temperature`/`seed` is set, so it may be a guaranteed-identical failure that costs a
   second full copy of the description.

**Why deferred, not dismissed:** measured across all 259 real completed responses — max
evidence 259 chars against a 500 cap, max reason 285 against 1000, max
`required_experience` 171 against 200. **Zero violations, zero 1–3 character evidence.** The
4 empty-evidence rows are all `seniority_match: uncertain` with reasons stating no
eligibility criteria were given, which is the prompt working as instructed.

**Reopen if:** the model changes, a provider's behaviour shifts, or a response is ever
observed approaching the old caps.

**Related, also deferred:** prompt injection has no defence — scraped descriptions are
concatenated with no delimiters or instruction hierarchy. Mitigating context is that this
is a personal tool and the threat is SEO-spam postings, not a security boundary. Evidence
validation cannot help here: injected text is genuinely part of the description, so quoting
it is verbatim-valid.

---

## D9. 180-company backlog descoped
**2026-09-30 · SETTLED · user decision**

~150 sources enabled; 174 of the 180 backlog companies were `search_only` and are shelved.
`data/company_seed.csv` still lists all 330 as the seed, so accounting reports cover them —
but they are not in play.

---

## D10. Pre-rewrite documentation archived, not deleted
**2026-10-01 · SETTLED**

`docs/01`, `02`, `03`, `implementation_progress` and `source_discovery_workflow` moved to
`docs/archive/` with banners.

**Why archived rather than deleted:** `03` is the only definition of the H0–H11 checkpoints
that other documents cite by name, and `implementation_progress` holds the per-company
activation forensics — why each source was enabled, and why NVIDIA, PayPal, LinkedIn,
Flipkart, Roku and Microsoft failed closed. That evidence exists nowhere else.

**Why they could not stay in place:** `AGENTS.md` instructed every agent to read them as
authoritative, and they describe a narrow title filter and a seniority-only LLM call. An
assistant following them would have built the wrong thing.

---

## D9. Persist the discarded evidence, and the description with it
**2026-10-01 · DECIDED** (migration 5)

Closes the "relevance evidence is not persisted" open question below.

**What was wrong:** the merged call returns a validated verbatim quote and a reason for
all three judgments. `merged_evaluator` built a `SeniorityDecision` from five of the
judgment's fields and dropped the rest, so only the `verdict` enum reached SQLite. The
judgment rejecting ~59% of evaluated jobs (153 of 259 in the 2026-09-30 run) was the one
nobody could explain after the fact. Descriptions were likewise unstored, so no judgment
could be re-derived without re-scraping.

**Measured cost.** Against the 259 completed rows in `jobs-pre-rescan-20261001.sqlite3`:
`seniority_result_json` is median 371 bytes, max 566 (`reason` median 151 / max 285;
`evidence` median 93 / max 259). Adding relevance and location evidence roughly doubles
that — **~2.5MB across a full 3,677-job scan**, against a 3.7MB database. Descriptions are
the expensive half at ~23kB each, ~85MB for a first full scan, then slow growth: the
10-day recency window bounds each run's intake, and an evaluated job is never re-fetched
because the cache keys on `description_hash`.

**No re-evaluation.** The cache key is `description_hash` + `profile_version` +
`prompt_version` + `model_policy`. A schema migration touches none of them, so this was
not a ~$7 re-scan. **No backfill is possible** — the discarded text is gone, so a row can
legitimately carry a verdict with NULL evidence. Consumers must tolerate that pairing.

**Prune nulls, never deletes — the load-bearing part.** `collection.py:419` reads
`jobs.first_seen_at` as the recency basis whenever a source lacks a verified publication
date. Deleting a row makes a still-live job look newly-seen: it re-enters the funnel, is
re-evaluated at cost, and resurfaces as new. It would also bypass
`MINIMUM_SIGHTINGS_TO_EXPIRE = 2` and `COLLAPSE_RATIO = 0.5`, the guards that stop a
truncated scrape closing live jobs. Nulling reclaims essentially all the space because the
description is the only large column. Filter on `last_seen_at`, never `first_seen_at`.
Verified on 500 seeded jobs: 8.4MB reclaimed, all 500 rows and hashes intact.

**Bug found while wiring this up:** the `JobRecord` passed to `_record_decision` was
fetched before `record_verdict` ran, so it predated the verdict it reported. Every row
would have shown a blank relevance on the run that judged it and picked one up only on a
later cached run — a failure that looks correct the moment you re-run to check.

**No `maxLength` bounds added.** D8 deferred those on measured evidence; adding them here
would have reversed that silently.

---

## Open questions — not yet decided

- **Concurrency.** The pipeline is single-threaded throughout. `max_workers` exists in
  `collection.py` but is unreachable: it defaults to 1, nothing passes it, no CLI flag. The
  pool is written and tested but dead. Note that 39 companies share
  `boards-api.greenhouse.io` and the rate limiter is keyed by host, so added workers would
  queue there regardless.
- **Timing instrumentation.** `candidate_evaluation` reports no `seconds=` and no HTTP/LLM
  split, unlike the other two phases. Three separate performance diagnoses were wrong
  because this data does not exist. **Measure before optimising.**
- ~~**Relevance evidence is not persisted.**~~ Resolved by D9 (migration 5).
- **The relevance evaluation set is inert.** 20 cases exist; every test asserts things
  about the JSON file and none run it against a model. No accuracy gate, unlike the
  seniority path's 90% agreement gate.
- **`filters/description_relevance.py` is dead code** — imported only by its own test. The
  regex gate it implements was removed (`to_change.md` 2.3). Delete it with its test, or
  record why it is retained.
- **Amazon geo-filter pollutes diagnostics** (`PS_Note.md` L112-115): `amazon_jobs.py:354`
  raises on a geo-filter rejection, so intentionally filtered jobs are recorded as
  `malformed_job` — corrupting the signal meant to detect broken adapters.
