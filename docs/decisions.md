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
**2026-09-30 · SUPERSEDED for the daily CLI by D12 · commits `0fe8d3e`, checkpoint module**

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

The cache/fetch behavior below records migration 5. D12 supersedes it for the daily CLI:
fresh scans fetch retained descriptions again and reuse only exact-request judgments.

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


## D12. Daily database batches and independent evaluation attempts
**2026-10-01 · SETTLED · user-approved implementation plan**

Discovery publishes a full frozen batch in SQLite before any LLM call. A fresh scan
invalidates the previous batch; fatal discovery failure requires another scan. Healthy
sources may form a partial batch. `evaluate` resumes the current attempt and
`force_reevaluate` restarts the entire saved batch under current evaluation rules.
Admission expires at midnight IST; an already admitted invocation may finish.

**Why:** the previous budget-only JSON checkpoint could not recover a crash, omitted
completed results and coverage, and was not included in SQLite backup/restore. Batch,
complete merged judgment and progress need one transactional authority. Spending remains
independent of replaceable data and is marked discarded instead of subtracted. Same-day
lifecycle replacement must recompute from a baseline rather than count repeated runs.
This supersedes D6's file checkpoint and sliding 24-hour deadline for the daily CLI.

**Replacement boundary:** a fresh scan discards replaceable batch/artifact data, not
durable job identities, first-seen dates or spending. Erasing identities would make old
undated jobs look new and break the recency contract. Fatal discovery never publishes
partial job/lifecycle changes. Individual source failures still permit a partial batch
when another source succeeds or returns a verified empty board.

**One day, one observation:** daily lifecycle changes are recomputed from the pre-day
baseline on replacement. Presence includes all normalized source listings before the
recency/location/title filters; otherwise an aged-out but still-listed job would look
absent. Source collapse checks compare against an earlier trustworthy date, rather than
the run being replaced. Only the current day's baselines and current/most recent earlier
trustworthy company counts are retained after publication. Regression tests cover
same-day sightings/absences, aged-out presence and a collapsed source.

**Exact request cache:** store complete judgments keyed on the rendered request and
model policy, including title and prompt contents. A description-only cache would miss
title changes and could promote a cached unrelated rejection into a match. Legacy cache
entries lack this proof and deliberately miss once. `evaluate` rejects changed evaluation
rules; `force_reevaluate` allows those changes but cannot rebuild a batch selected under
different sources or discovery filters. Those require a fresh scan.

**Provider recovery and spending:** journal before sending; persist returned content and
usage before validation; atomically commit the complete judgment and candidate progress.
Saved replies replay without reserving the next invocation's request budget. A regression
test showed that charging the replay against a one-request cap prevents the validation
retry forever. Keep the existing bounded validation retry; this is recovery, not the
broader retry-policy redesign deferred in D8. Returned malformed replies still incur
usage; missing provider usage stays unknown even when the judgment is valid. Unknown
usage reserves a conservative output bound for the current invocation.

**No exactly-once billing claim:** a process can die after provider acceptance but before
persisting a reply. Keep that request's usage unknown and allow a new request on resume;
it may charge again. Removing the row or treating it as zero would understate spending.
Typed, idempotent usage and discard events supplement permanent SQLite request records.
Totals include discarded spending, group currencies separately and assign requests to
the actual request date in IST. An old database restore must not undo discard markers
already exported to the ledger. Prices are still the configured estimates under D7.

**Operator safety:** admission, dated log/report replacement, request exports and reset/
prune mutations use the same OS lock. Reports represent the whole saved attempt after
resume, including cached/known matches and explicit pending counts. Exit 6 distinguishes
an evaluation halt from completed coverage. An active invocation may cross midnight;
another invocation then requires a fresh scan. Legacy JSON checkpoint flags are rejected
explicitly rather than silently ignored; SQLite backups include batch/progress.

## D13. Explicit discovery-only stopping point
**2026-10-01 · SETTLED · user request**

`scan --discovery-only` publishes the same complete batch, full retained descriptions,
coverage and lifecycle as a normal scan, then skips the evaluation stage entirely,
including cache reuse. Every retained candidate stays pending for a later `evaluate`.
Keep the normal configuration fingerprint and midnight IST admission limit, so later
evaluation obeys D12's consistency and freshness guards.

**Why:** intentionally delaying LLM calls should not depend on manipulating a token cap,
timing an interrupt, or producing a budget error. Successful discovery returns coverage
status 0/2 while terminal/JSON/Markdown explicitly say evaluation was deferred. Budget
halts still return 6. The flag is rejected on evaluation/resume commands before any
state/artifact replacement; otherwise an operator could silently skip the requested
evaluation. Current provider/model/prompt settings remain required to bind the frozen
batch to its eventual evaluation rules. No network inference is performed in this mode.

---

## D14. Adapter entity checks identify the company, not an exact legal name
**2026-10-01 · SETTLED**

`navi_careers.py` rejected any `CompanyName` outside the literal set
`{"Navi", "Navi Limited"}`. Navi's public API reports the *legal entity* that owns each
requisition, and 4 of 36 live jobs are owned by `NAVI TECHNOLOGIES LIMITED` — the holding
company's former name, still attached to open requisitions after its rename to Navi
Limited. Those rows raised `malformed_job`.

The check now requires only that the first word of the name be exactly `navi`, which
accepts the group's entities (`Navi Finserv Limited`, `Navi General Insurance Limited`)
while still rejecting an unrelated company that merely contains the substring
(`Navigator Systems`, `NaviLink`).

**Why:** the entity string is not the relevance signal — `filter_role` and the LLM gate
decide that. This check exists only to prove a posting is not an unrelated company sharing
the endpoint. Pinning it to exact display names makes the adapter fail on ordinary
corporate action (renames, subsidiaries, acquisitions) with no warning until a run reports
the source as degraded.

**How to apply:** when an adapter must confirm a payload belongs to its company, match the
company identity, not a fixed display string. Prefer a rule that survives a rename.

---

## D15. A malformed row degrades the row, not the whole source
**2026-10-01 · SETTLED**

`navi_careers.py` returned immediately on the first unparseable row. Combined with D14,
the 2026-10-01 run retained **4 of Navi's 36 jobs** — the abort fired at index 4 and
discarded the 31 valid rows after it. `greenhouse.py` and `ashby.py` already skip the row
and continue; Navi now does the same, and reports `PARTIAL` with `complete=False` whenever
any row failed.

**Why:** one unparseable row is evidence about that row. Dropping every subsequent job
turns a single upstream quirk into near-total silent data loss on a healthy source, and
the resulting count still looks like a plausible result. Completeness is reported through
the outcome and the `complete` flag, which is what downstream coverage accounting reads —
an early return is not needed to signal it, and actively destroys information.

**How to apply:** per-row validation failures append a `malformed_job` diagnostic and
`continue`. Reserve early returns for whole-response faults — bad JSON, failed total
reconciliation, duplicate identity, redirects — where later rows genuinely cannot be
trusted.

---

## D16. `inconsistent_total` on Eightfold is correct behaviour, not a bug
**2026-10-01 · SETTLED · no code change**

Millennium Management (`eightfold`, tenant `mlp`) reported `source_retry_exhausted` +
`inconsistent_total` and outcome `suspicious` on 2026-10-01. Investigated and
**deliberately not fixed.**

Replayed the same public endpoint the same evening: 22 pages, 214 jobs, `count` stable at
214 across every page, 214 unique IDs, zero duplicates. The adapter paginates correctly.
`inconsistent_total` fires only when Eightfold's `count` changes *between pages of one
run*, which is what happens when a requisition is opened or closed mid-pagination — the
source is genuinely in motion and completeness for that run is unknowable. The source was
validated at 225 jobs on 2026-09-21 and serves 214 now, so this board does change.

The outer retry already treats `SUSPICIOUS` as retryable (`base.py:116-120`); it retried
and the count moved again each time, which is exactly `source_retry_exhausted`.

**Why not "fix" it:** the only ways to make this green are to tolerate a drifting count or
to stop reconciling totals, both of which would let a genuinely truncated page set be
recorded as complete. Reporting one company as `suspicious` for a run is the correct,
conservative outcome and does not affect the other 148 sources.

**Reopen if:** this company fails this way on most runs rather than occasionally, which
would suggest the board mutates continuously and needs a different completeness strategy
(e.g. snapshot-and-verify) rather than a loosened check.

**Known-latent, deliberately not fixed in D14/D15:** a `malformed_job` ERROR forces
`complete=False`, and `safe_for_absence_counting` (`source_contracts.py:201-208`) then
blocks absence counting, so a permanently-unparseable row would stop Navi jobs expiring
and make the source retry 3× every scan for a byte-identical result. Measured 2026-10-01:
all 36 live Navi rows normalize, so no row is currently in this state. Fixing it properly
means separating "this row belongs to another company" (a filtering decision, severity
WARNING, completeness untouched) from "this row is defective" (a parse defect) across all
adapters, not just Navi. **Reopen if** any adapter reports a non-zero steady-state
`malformed_job` count across consecutive runs.

---

## D17. Porter's empty descriptions are empty at the source, not an adapter bug
**2026-10-08 · SETTLED · no code change**

Porter (Darwinbox tenant `porter`) returned `empty_description` for 67 of its 119 jobs on
2026-10-07. Checked against the raw API and Porter's own UI, not inferred from our output.

Raw `jd` from `/ms/candidateapi/job/<id>` for all 119 jobs: 52 carry text, 26 are `""`, and
41 are markup with no text (`&lt;p&gt;&lt;br /&gt;&lt;/p&gt;`). 26 + 41 = the 67 reported. The
detail payload has no other description-like field (every other string is a location). The
listing endpoint's `jd` is empty for all 119, which is why detail is needed at all.

Porter's own page for a Business Associate posting (rendered in headless Chrome) shows
"No job description at the moment!" with only title, location, department and employee type.
`_plain_text` (`darwinbox.py`) stripping markup-only `jd` to `None` is therefore correct.

**Why:** the title-only judgment (`NO_DESCRIPTION`) is the right behaviour for these jobs, and
the daily re-fetch picks up a description if Porter ever adds one. ClearTax and Unacademy use
the same adapter; their pages also render with no description ("No job description at the
moment!" and "Please enter job description").

**Fixed 2026-10-09:** the canonical URL we stored, `/ms/candidate/careers/<id>`, lands on the
tenant home page in a browser. `_job_url` now builds the page that renders the posting,
`/ms/candidatev2/main/careers/jobDetails/<id>`, verified on the porter, clear and unacademy
tenants. Job identity uses the external ID, so no job key changes, and stored rows take the new
URL the next time they are observed.
