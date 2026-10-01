# to_change.md — agreed changes, not yet built

Running record of design decisions that are **still open**. Everything the original
rewrite spec called for has been built and shipped; the history of those decisions now
lives in git and in `CLAUDE.md`.

Status key: **PROPOSED** needs a call · **DECIDED** settled, not yet built ·
**DEFERRED** revisit later (with a stated trigger)

**State of play (2026-10-01):** the four-phase rewrite is complete. Phases 0–4 —
logging, exception taxonomy, normalization canon, the `_support.py`/`validation.py`
extraction, the `collection.py` rename, rate limiting, parallel collection scaffolding,
the 2.2a blocklist, the merged LLM call, three-way verdicts, the lifecycle state machine,
the §4 schema columns, and the expiry dry-run — are all in `src/`. Sections 1–6, 9 and 10
of the previous revision of this file were verified against the code on 2026-10-01 and
removed as done.

What remains is one architectural change (§1 — decided 2026-10-01, ready to build) and a
short list of latent issues (§2) that are real but not urgent.

---

## Index

**1. Decouple candidate evaluation from collection — DECIDED, ready to build**
- 1.1 The problem · 1.2 Why the checkpoint doesn't cover it today
- 1.3 The design, incl. **(d) the `observe_listing` hazard — do not skip**
- **1.3c (e) checkpoint self-deletion · (f) report clobbering · (g) always-reports-success
  — three live bugs in `--resume` today; fix first, (g) is the priority**
- **1.3d Full systematic audit of the checkpoint path — confirms (e)(f)(g) are the
  complete set for existing consumers; everything else verified sound or honestly
  degraded**
- 🔴 **1.3f (j) `scan` is broken today — `TypeError` before collection; fix before all else**
- ⚠ **1.3c also holds the one genuinely open question: where recovered matches surface in
  the job feed. Decide before coding.**
- **1.3c also covers (k) empty-DB observation gap · 1.4d state-reset invalidates the
  3,677/$7.23 estimates**
- **1.3e (h) `evaluate` needs its own `ScanLock` · (i) no migration-version guard in
  `assert_resumable` — two gaps found stress-testing the not-yet-built `evaluate` command**
- 1.3a Why this over the schema version · 1.3b Its honest cost
- 1.4 The 3,026 stranded rows (this does *not* rescue them) · 1.4a Verify caps first
- **1.4b `evaluate` is recovery-only — decided, no `--reevaluate` override**
- 1.4c Checkpoint carries inline descriptions only; `evaluate` still hits the network
- 1.5 Staleness policy · 1.6 What this unlocks
- 1.7 Rejected alternatives · 1.8 Scope explicitly excluded · 1.9 Build order

**2. Known-latent issues** — documented, not urgent (mirrors `CLAUDE.md`)

**3. Explicitly deferred** — with triggers

---

## 1. Decouple candidate evaluation from collection — DECIDED 2026-10-01

> **Decision: make the existing resume checkpoint durable and general. Do not move the
> work queue into SQLite.** Reasoning in 1.3a; the schema version and its full column cost
> are recorded in 1.7 so the option isn't re-proposed from scratch.
>
> 🔴 **Blocked on (j): `scan` raises `TypeError` before collection and has been broken
> since `11234ae`** (1.3f). Fix that first — every plan below assumes a working scan.

### 1.1 The problem

The three scan stages are not independently re-runnable. `source_collection` and
`deterministic_filter` take ~3.5 hours and produce a `FilterVerificationReport` that
exists only in memory for the duration of one `run_manual_scan` call. `candidate_evaluation`
consumes it. If evaluation fails, is interrupted, or simply needs to run again with a
changed prompt, the only way back to the starting line is to re-scrape all ~150 sites.

This is not hypothetical. Measured on the 2026-09-30 run, still visible in `state/jobs.sqlite3`:

| `evaluation_status` | rows |
|---|---|
| `failed` (all `invalid_seniority_output` + "estimated LLM input-token limit reached") | **3,026** |
| `pending` | 392 |
| `completed` | 259 |
| **retained total** | **3,677** |

3,418 of 3,677 retained jobs — 93% — have no verdict. The budget bug that caused it is
fixed (`df0c60d`), and `_needs_processing` (`scan.py:870-880`) already recognises the
recorded error text and will retry those rows. But it can only do so during a full scan,
so recovering a $6.84 LLM pass costs 3.5 hours of scraping that has nothing to do with
the failure.

The same five `KeyboardInterrupt` runs recorded in `scan_runs` on 2026-09-30 tell the
same story from the other direction: every interruption during or near evaluation paid
the full collection tax again on the next attempt.

### 1.2 Why the existing checkpoint doesn't cover it

`checkpoint.py` already solves a *narrow* version of this: when evaluation halts on
budget exhaustion, `_write_resume_checkpoint` (`scan.py:509`) snapshots the unprocessed
tail to `state/resume_checkpoint.json`, and `scan --resume` replays it. That mechanism is
correct and well-built. Its limits are structural, not accidental:

- It is written **only** on budget halt — not on interrupt, crash, or clean completion.
- It is **deleted on any clean finish** (`scan.py:809-810`), so it is single-use.
- It expires after 24h (`STALENESS_LIMIT`).
- It holds only the *tail*, so it can never answer "re-evaluate everything."

The result is that the 3,026 rows above have no checkpoint, because the run that stranded
them eventually completed. The recovery path exists in `_needs_processing` but has no
cheap way to be invoked.

### 1.3 The proposal — make the checkpoint durable, not exceptional

**Decision: keep the work queue in `state/resume_checkpoint.json`; do not migrate it into
SQLite.** The reasoning is in 1.7; the short version is that `CheckpointRow` already
carries exactly what evaluation needs and `jobs` does not come close.

Three changes, all small:

**(a) Write the checkpoint on every run, covering all retained rows.** Today
`_write_resume_checkpoint` (`scan.py:509`) fires only on budget halt and snapshots only
the unprocessed tail. Change it to write after the deterministic filter completes,
covering every retained row, before evaluation begins. The evaluation loop then updates
`evaluated_before_halt` as it advances.

**(b) Retain the checkpoint while retryable work remains.** ⚠ *Corrected — an earlier
draft said "stop deleting it on clean finish" and justified that by re-evaluating against
a new prompt, which 1.4b expressly forbids. The justification was wrong and the rule was
too broad.*

The correct rule follows from `evaluate` being recovery-only: **a checkpoint is worth
keeping exactly as long as it describes work that could still be retried.** So the unlink
at `scan.py:809-810` becomes conditional on retryable work remaining, not on
`budget_halted` alone:

- Retained when any row in the checkpoint's scope is still `pending`, budget-halted, or
  `failed` with a retryable `reason_code` (`_needs_processing` is the predicate — reuse
  it, don't reimplement).
- Deleted when every row has a verdict. A fully judged run has no recovery work, so its
  checkpoint is dead weight and keeping it only invites a stale `evaluate`.

This preserves the property change (b) is actually for — a crash, interrupt, or provider
outage after evaluation starts no longer costs 3.5 hours — without implying the corpus
re-judging that 1.4b rules out. It also means the file is usually absent on a healthy
system, which is the right default.

**(c) Add the command:**

```
job_finder evaluate [--checkpoint PATH] [--limit N] [--company-id X] [--dry-run]
```

It reads the checkpoint, calls `assert_resumable` unchanged (1.4b), filters to rows where
`_needs_processing` holds against the live DB, and calls the existing
`process_filter_report` with `run_lifecycle=False`. That last flag is not optional — a
partial row set must never drive absence detection, which is the same constraint
`resume_from_checkpoint` already documents.

`scan --resume` then becomes a thin alias for `evaluate` over the same file, and
`resume_from_checkpoint` collapses into it.

There is deliberately **no** `--reevaluate`, `--force`, or version-override flag (1.4b).
If the config has changed, the command fails with the existing error and tells the
operator to run a full scan.

**(d) ⚠ Guard the `observe_listing` side effects.** This is the one genuine hazard and it
is not hypothetical. `process_filter_report` calls `repository.observe_listing` for every
row (`scan.py:611`) *before* the `_needs_processing` check (`scan.py:617`), and that call does two
things an evaluation pass must not do:

- **It writes `last_seen_at = observed_at`.** Under `evaluate`, `observed_at` comes from
  the checkpoint's `scan_at` — an old timestamp — but the row is being touched now. Worse,
  if a future `evaluate` passed "now" instead, it would manufacture a sighting for a job
  nobody re-observed, feeding the §3 lifecycle machinery with fiction. `days_active` is
  defined as `last_seen - first_seen` (§4.2a), so this corrupts reported durations.
- **It can reset a completed verdict.** When `description_hash` differs from the stored
  one, the UPDATE at `repository.py:132-145` sets `evaluation_status = 'pending'`,
  `prompt_version = NULL`, and `seniority_result_json = NULL`. A re-fetched description
  that changed since collection therefore *discards an existing verdict* — correct during
  a scan, but during `evaluate` it silently enlarges the work set and destroys prior
  judgments.

**Required:** `evaluate` must either pass the checkpoint's original `scan_at` as
`observed_at` (never "now"), or take an explicit `observe=False` path that skips the
sighting write entirely. The second is cleaner and worth the small refactor —
`observe_listing`'s docstring says "persist observation before description retrieval,"
which is a scan concern, not an evaluation one.

**Test this explicitly:** after `evaluate`, assert `last_seen_at`, `sighting_count`, and
`consecutive_absences` are byte-identical to their pre-run values for every touched row.
Without that test this bug is invisible until lifecycle data is already wrong — and per
the working agreements, a transient condition must never be recorded as per-job state.

**Descriptions are already stored in the checkpoint — and must stay that way.**
⚠ An earlier draft of this section said the opposite ("descriptions stay unstored,
re-fetch is cheap"). That was wrong, and the code already knows why.
`_job_as_json` (`checkpoint.py:252-255`) carries `description`, with a comment explaining
the decision: roughly a third of listings carry the description inline from the listing
payload, so omitting it *forces the resumed run to make an HTTP request the original never
needed* — which can fail and send the row to review instead of to the model. That is
silent corpus loss, not a saving.

The measured numbers confirm it: 2,447 of 3,677 retained rows needed a detail fetch, so
**1,230 (33%) had the description inline**. By source count the split is starker — **92 of
150 enabled sources are `listing_payload`**, i.e. description-inline. Dropping descriptions
from the checkpoint would put those rows at risk of `description_unavailable` on every
re-evaluation.

This does **not** reopen the settled "don't store descriptions *in SQLite*" decision —
that remains correct. The checkpoint is a transient work queue, not the durable store.

**Consequence — checkpoint size.** Upper bound ~23 kB × 3,677 ≈ **85 MB**, against the
"~30 MB at worst" its comment estimates (that figure predates 2.2a widening the retained
set). The real file is smaller because only inline-description sources contribute text —
see 1.4c. Written atomically via `.tmp` + `replace`, so peak disk is ~2×. Acceptable, but
it must be a conscious choice:

- `state/` is gitignored — confirm before shipping, since an 85 MB file must never be
  committed.
- Write it **once** after the filter completes, not incrementally per row. Re-serialising
  85 MB on every job would dominate evaluation time.
- Progress through the corpus is tracked in `jobs.evaluation_status` (already durable per
  row), not by rewriting the checkpoint. `evaluated_before_halt` stays a coarse hint only.

**Size of the change:** one moved call site, one deleted line, and a CLI command wrapping
an existing function. No migration, no backfill, no new serialization format.
`checkpoint.py`'s version guards, staleness check, and `assert_resumable` are reused
as-is.

### 1.3c ⚠ Two more places the change leaks — found in round-4 review

Both are consequences of `evaluate` reusing the scan's plumbing. Neither is visible from
the design sketch; both are load-bearing.

**(e) `evaluate` would delete the checkpoint it just used.** `process_filter_report`
unlinks `checkpoint_path` on any non-budget-halted finish (`scan.py:808-810`), and
`resume_from_checkpoint` passes `checkpoint_path` straight through
(`scan.py:421`). So the *first* successful `evaluate` destroys the durable checkpoint that
change (b) exists to preserve — silently converting the new design back into the
single-use one, and taking the recovery path with it if the next run also fails.

⚠ **(b) and (e) as written contradict each other**, caught in review: (b) says delete the
checkpoint once no retryable work remains, (e) says `evaluate` passes
`checkpoint_path=None` so it can never delete. Both cannot hold. Resolution:

**`process_filter_report` must not own checkpoint deletion at all.** It is an evaluation
routine; deleting the operator's recovery file is not its concern, and the coupling is
what produced (e) in the first place. Remove the unlink from it entirely and make
retention an explicit decision by each caller, after the run:

- **`scan`** — writes the checkpoint after the filter (a); on finishing, deletes it only
  if no retryable work remains in its scope (b).
- **`evaluate`** — same rule, but **only when it processed the whole checkpoint.** With
  `--limit` or `--company-id` it has seen a slice, knows nothing about the remainder, and
  must **always retain** the file. Deleting on a slice would discard unexamined work —
  the precise failure (e) describes, reintroduced through a flag.
- Neither deletes on crash or interrupt; retention is the safe default in every ambiguous
  case.

**`--dry-run` semantics, defined before the flag exists** (it was listed in the command
sketch without meaning): report what *would* be evaluated — count, companies, and the
reason each row qualifies — while making **no** LLM calls, **no** writes to `jobs`, **no**
report output, and **no** checkpoint deletion. It is a planning command. In particular it
must not create observations (k), since that is a write.

The original framing of (e) below stands as the diagnosis; the fix is the above rather
than `checkpoint_path=None`.

The unlink is correct for `scan` (a completed scan's checkpoint is genuinely superseded)
and wrong for `evaluate` (its input is not its own output). Required: `evaluate` passes
`checkpoint_path=None` so `process_filter_report` cannot delete it, and handles any halt
of its own separately. Corollary — with (b) removing the unlink from the scan path too,
audit **every** `checkpoint_path` caller rather than just the two obvious ones; the
deletion currently happens in a function neither caller expects to mutate the filesystem.

**(f) `evaluate` would overwrite `reports/latest_scan.json` with a partial report.**
`cli.py:1079-1080` calls `write_scan_report` / `write_scan_markdown` unconditionally on
whatever `report` comes back, and `--resume` already flows through that same tail. But a
checkpoint-derived report is a deliberately reduced object: `_report_from_checkpoint`
sets `companies=()`, `zero_retained_companies=()`, `listing_count` = slice size, and
`final_counts` = `{retained: slice}` — its own docstring says the counts "describe the
checkpoint slice, not the original scan."

So running `evaluate` replaces a 42,116-listing report that has full company accounting
with one describing a few hundred rows and **no company data at all**. That is the file
1.4 relies on as the backfill source of record, and the one the eventual website reads.
It is also how a partial run could be mistaken for a full one after the fact.

Required: `evaluate` writes to a distinct default path (`reports/latest_evaluate.json`),
or takes explicit `--json-output` / `--markdown-output` with no default that collides with
the scan's. Prefer the former — a default that silently destroys the previous run's
report is exactly the kind of footgun the working agreements warn about.

**⚠ But separate files are only half an answer — the jobs must still reach the feed.**
`ScanReport.matching_jobs` is built from `matches`, appended inside *this invocation's*
evaluation loop (`scan.py:1091`, emitted at `834`). It is a record of what this run
judged, not a query over the store. So after the split above:

- `latest_scan.json` keeps full company accounting but **its job lists omit every match
  the recovery run found** — the scan never evaluated those rows.
- `latest_evaluate.json` holds the recovered matches but has `companies=()`, zeroed
  source counts, and `registry_version="resume"`.

Neither file is the answer on its own, and "check both" is not a design — it guarantees
that whoever builds the feed silently reads one of them.

**This is the real unresolved question in §1, and it should be settled before writing
code.** Three options, with my recommendation:

1. **Derive the feed from SQLite, not from run reports.** The `jobs` table already holds
   `verdict`, `verdict_at`, `status`, and (per §3.6) the feed is meant to sort on
   `verdict_at` anyway. Run reports become what they honestly are — per-run operational
   records — and no longer double as the product surface. **Recommended.** It removes the
   coupling permanently rather than patching one instance of it, and §3.6's "New today
   keys on verdict, not first sighting" already assumes a store-backed feed.
2. **Have `evaluate` merge its matches into `latest_scan.json`**, preserving the scan's
   accounting and appending job records. Rejected: it makes a report mutable after the
   fact, so `latest_scan.json` would no longer describe any single run, and two writers
   would race for one file.
3. **Regenerate `latest_scan.json` from the DB at the end of any run.** Closer to (1) but
   keeps the misleading filename and still conflates operational metrics with product
   data.

Until this is decided, **`evaluate`'s output is operational only** and must not be
presented as the job feed. Note the same gap exists today for `--resume` — its matches
have always been confined to the resume report — so this is a pre-existing coupling the
change exposes rather than creates.

**Test both:** after `evaluate`, assert the checkpoint file still exists and
`reports/latest_scan.json` is byte-identical to its pre-run contents.

**(k) The `observe=False` guard breaks when the DB has no row yet.** Change (d) said
`evaluate` should skip `observe_listing` to avoid fabricating sightings. That is right for
rows already in `jobs`, and wrong for rows that never got there.

Change (a) writes the checkpoint *after the filter, before evaluation* — so if the run
dies before reaching a given row, that row has a checkpoint entry and **no `jobs` row at
all**. This is not a corner case: it is precisely the crash-early scenario (a) exists to
survive, and it is also the state after any deliberate state reset.

With a strict `observe=False`, those rows have no record to update and `evaluate` cannot
process them — the recovery tool fails at the exact moment recovery is needed.

**Required:** `evaluate` must *create* a missing observation, at the checkpoint's original
`scan_at`, while never modifying an existing row's `last_seen_at`, `sighting_count`, or
`consecutive_absences`. Insert-if-absent, never update-if-present. The distinction (d)
was reaching for is not "don't observe" but "don't re-observe."

**Test:** run `evaluate` against an empty `jobs` table and assert every checkpoint row is
evaluated with `first_seen_at == last_seen_at == checkpoint.scan_at`; then re-run against
a populated table and assert those three fields are untouched.

**⚠ Both defects are live in shipped `--resume` today — they are not introduced by this
change.** Verified 2026-10-01: `resume_from_checkpoint` passes `checkpoint_path` at
`scan.py:421`, and `--resume` shares the unconditional `write_scan_report` tail at
`cli.py:1079-1080` with `scan` (same `--json-output` default,
`reports/latest_scan.json`).

Consequences today, independent of anything proposed here:

- A successful `--resume` deletes its own checkpoint. Correct-ish by accident, since the
  checkpoint really is consumed — but it means a *second* budget halt during the resume
  writes a fresh checkpoint over the old one, which is fine, while any non-halt failure
  afterwards leaves nothing to resume from.
- A successful `--resume` overwrites `reports/latest_scan.json` with a
  company-less, slice-sized report. **This is likely what happened on 2026-09-30**: the
  run recorded as `partial` with `evaluated=140` has a full 42,116-listing report, so the
  report survived there — but any future resume would have silently replaced it, taking
  the 1.4 backfill source with it.

This raises the priority: fixing (e) and (f) is worth doing **whether or not** the rest of
§1 proceeds, and the fix is the same either way. Treat them as bugs, not as design work,
and land them first.

**(g) ⚠ A resume always reports success — including when it halts on budget.** The worst
of the three, and also live today.

The chain, verified 2026-10-01:

1. `_report_from_checkpoint` sets `companies=()` (`scan.py:451`, function definition).
2. `FilterVerificationReport.healthy` is `all(... for company in self.companies)`
   (`collection.py:147-151`). **`all([])` is `True`** — vacuously healthy.
3. `_scan_outcome` returns `ScanOutcome.COMPLETE` on `report.healthy`
   (`scan.py:1245-1247`).
4. `runs.finish(status=_run_status(outcome))` records **`completed`**, and
   `cli.py:1167` returns `report.outcome.exit_code` → **0**.

So `--resume` reports `scan=complete`, writes `status=completed` to `scan_runs`, and exits
**0** regardless of what actually happened — including a second budget halt that left
thousands of rows unevaluated, or every LLM call failing. The `HALTED_ON_BUDGET` notice is
printed to the progress stream, but the machine-readable signals all say success.

Why it matters more than (e) and (f): those lose data recoverably. This one **lies to
automation**. Under cron or any wrapper keying on exit status, a resume that accomplished
nothing is indistinguishable from one that finished the corpus. It is the same class of
defect as the §6 headline finding that started this whole rewrite — *"the system is
structurally incapable of telling you when it breaks"* — reintroduced in the one code path
added after that audit.

It also interacts with the working agreement about transient conditions: budget halt is
already correctly kept out of per-job state (`df0c60d`), but it is not reflected in
**run** state, where it belongs.

**Required — and my earlier one-line fix was wrong.** I previously wrote "make `healthy`
reject zero companies." That breaks the checkpoint path: a *successful* `evaluate`
legitimately has `companies=()`, so it would be reported `FAILED`. The bug and that fix
would cancel out into a different wrong answer.

The real defect is that **one axis is being used to answer two questions.** `ScanOutcome`
currently means "did the sources behave," and the code then reads it as "did the run
succeed." Those diverge the moment evaluation can fail independently of collection —
which is exactly what a budget halt is, and what `evaluate` makes routine.

So separate them:

- **Source coverage** — unchanged semantics, derived from `companies`. Not applicable on
  the checkpoint path; represent that as *not applicable*, never as vacuous success.
- **Evaluation completeness** — derived from the counts that already exist:
  `llm_budget_halted_count`, `description_failure_count`, and the residual
  `_needs_processing` population. A run with budget-halted rows is **not** complete
  regardless of how the sources behaved.

Run status and exit code come from combining the two, with "not applicable" contributing
nothing rather than passing. This also fixes the *scan* side of the same bug, which (g)
as originally written did not address: **a `scan` that halts on budget currently reports
`COMPLETE` and exit 0 too**, because its sources were healthy — the 2026-09-30 run is
recorded `partial` only because three companies failed, not because 3,026 jobs went
unevaluated.

Acceptance criterion (adopted from review): **every row retained by the run has either a
completed verdict or an explicit, accurately reported reason it is unfinished.** That is
the property worth testing, and it is meaningful on both paths.

**Terminal vs unfinished — the distinction the counts alone cannot make.** ⚠ A second
review round found that the three counts named above are insufficient, and the reason
matters.

When the model returns output that fails schema or evidence validation, `service.py:148`
writes a **terminal** `failed` row: `pipeline_disposition=manual_review`,
`reason_code=invalid_seniority_output`. Verified 2026-10-01 against `_needs_processing` —
that row is **not** retryable under an unchanged prompt and model: it matches no retryable
`reason_code`, carries no `"limit reached"` error text, and its version fields match. It
only becomes retryable when the prompt or model changes, which 1.4b routes to a full
`scan`.

So a run where **every** evaluation produced invalid output has
`llm_budget_halted_count == 0`, `description_failure_count == 0`, and zero residual
`_needs_processing` rows — and would be reported `COMPLETE` under the rule as I first
wrote it, contradicting this section's own test that an all-failed evaluation must not be
`COMPLETE`.

**Decision: terminal review is *completion*, not *incompleteness* — but it is not
success.** The three states are distinct and the status model must carry all three:

| State | Meaning | Contributes to |
|---|---|---|
| Verdict reached | judged | success |
| **Terminal review** (`manual_review`) | we judged it and the output was unusable; nothing more to try under this config | **completed, not successful** |
| Unfinished (budget halt, provider failure, description unavailable, pending) | we did not get to it; retry will help | **incomplete** |

Restated criterion: **every retained row ends in exactly one of — a verdict, a terminal
reason recorded against it, or an accurately reported unfinished state.** A run with no
unfinished rows is `COMPLETE`; a run whose terminal-review share is abnormal is complete
*and* should be loud about it, because a spike there means the prompt or the schema
broke, not that the corpus is hard.

**Therefore add a fourth signal: terminal-review rate.** It is already computable
(`counts.review` exists). A run that reaches the end with, say, >20% terminal review
should not exit 0 silently — that is the "structurally incapable of telling you when it
breaks" failure returning in a new costume. Treat a threshold breach as `PARTIAL`.

This also retires the working agreement's trap in the other direction: budget exhaustion
must never be recorded as terminal (fixed in `df0c60d`), and terminal review must never be
recorded as unfinished. They are different states and the schema now distinguishes all
three.

**Test:** a resume that halts on budget must record `status != completed` and exit
non-zero; a resume where every evaluation fails must not report `COMPLETE`.

**The same vacuous truth reaches `scan`, not just resume.** `companies` is built from the
*enabled* registry entries (`collection.py:573,608`), so a registry where everything is
disabled — a bad config edit, a botched merge of `company_sources.json` — produces
`companies=()`, `healthy=True`, `COMPLETE`, exit 0, and a report saying nothing is wrong.
Currently 150 of 330 are enabled so it does not fire, but nothing prevents it, and the
failure is silent by construction. This is why fixing `healthy` is preferable to
special-casing the checkpoint path: **an empty company set is never evidence of health,
whichever command produced it.**

Suggested shape: `healthy` returns `False` when `companies` is empty, and `_scan_outcome`
additionally consults evaluation counts so a budget halt cannot report `COMPLETE`. Both
are small; the tests are what make them stick.

### 1.3f 🔴 (j) `scan` is broken right now — `TypeError` before collection

**Highest priority item in this file. Nothing else can be verified until it is fixed.**

`cli.py:1054` passes `checkpoint_path=args.checkpoint` to `run_manual_scan`, whose
signature (`scan.py:255-271`) has **no such parameter** and no `**kwargs`. Verified by AST
inspection 2026-10-01: keyword-only args are `database_path`, `lock_path`,
`source_retry_count`, `expiry_dry_run`, `job_probe`, `connectivity`, `on_item_start`,
`started_at`, `run_id`, `progress`.

So **every plain `python -m job_finder scan` raises
`TypeError: run_manual_scan() got an unexpected keyword argument 'checkpoint_path'`**
before a single company is contacted. Only `--resume` works, because it calls
`resume_from_checkpoint`, which does accept it.

Introduced in `11234ae` ("resume a scan that halted on budget") — the resume path got the
parameter, the scan path got the call site, and the two never met. It is committed, not a
working-tree artifact.

**Why the suite did not catch it:** tests call `run_manual_scan` directly rather than
through the CLI, so the arity mismatch lives entirely in the untested seam between
`cli.py` and `scan.py`. Add a CLI-level smoke test that invokes the `scan` subcommand with
stub adapters; without it this class of breakage recurs.

**Consequences for everything above:** the 1.9 build order assumed a working `scan` for
step 3. It does not exist. (j) moves to the front, ahead of (e)/(f)/(g), and the "one
final full scan" plan is blocked on it.

**Fix direction:** `run_manual_scan` needs the parameter for real — it is what change (a)
requires anyway, since the scan path is where the checkpoint must now be written after the
filter. Do not silence it by deleting the CLI argument; that would remove the wiring (a)
depends on.

### 1.3d Complete audit of the checkpoint-derived path (2026-10-01)

The findings above were produced by spot-checking one assumption at a time, which is why
they arrived one per review round rather than all at once. This section is the systematic
version: every field of `FilterVerificationReport`, traced to every consumer reached when
the report comes from `_report_from_checkpoint` rather than `collect_listings`. It is
complete as of 2026-10-01 and supersedes the incremental notes.

**Method:** enumerate the 24 report fields; enumerate every `filtered.*` read in
`scan.py` (lines 305, 310, 527, 550, 586, 592, 598, 830, 840, 988, 1209-1226); check each
against what the checkpoint path actually supplies.

**Sound — verified, no action:**

| Consumer | Why it holds |
|---|---|
| `filtered.listings` (527, 592, 598) | Fully populated from checkpoint rows; the whole point of `CheckpointRow`. |
| `filtered.scan_at` (550, 586) | Carried through the checkpoint; `observed_at` is correctly the *original* scan time, not now. |
| `sources[row.company_id]` (609) | `registry.entries` holds all 330 including disabled, so a company disabled since the checkpoint still resolves. **Only** fails if a `company_id` is deleted from `company_sources.json` outright — a real but remote `KeyError`; worth a clear error rather than a crash. |
| `_run_lifecycle` (988) | Correctly skipped via `run_lifecycle=False`; the guard and its comment are right. |
| `ScanLock` (277, 396) | Both *existing* paths (`run_scan`, `resume_from_checkpoint`) take the same lock. ⚠ This table entry previously implied `evaluate` inherits that safety — it does not. `evaluate` is not built; `ScanLock` is acquired inside `run_scan`/`resume_from_checkpoint` themselves, invisible to `cli.py`, so a new `evaluate` function must explicitly wrap its body in `ScanLock(lock_path)`. Nothing does that automatically. Corrected in 1.3e below — treat as **action required**, not sound. |
| Cost ledger (`cli.py:1140-1156`) | Keyed off `report.usage` / `run_id`; works identically for a resume, and failure is explicitly non-fatal. |
| Budget-halt operator notice (`cli.py:1158-1166`) | Fires on `llm_budget_halted_count` regardless of path. |
| `filtered.timing` (840) | `None` on the checkpoint path; report writer tolerates it. |

**Broken — the three already documented, now confirmed as the complete set:**

| # | Field | Consumer | Effect |
|---|---|---|---|
| (e) | — | `checkpoint_path` (808-810) | Deletes the checkpoint it just consumed. |
| (f) | `companies=()`, slice counts | `write_scan_report` (`cli.py:1079`) | Clobbers `latest_scan.json` with a company-less report. |
| (g) | `companies=()` | `healthy` → `_scan_outcome` (1245) | `all([])` is `True` → always `COMPLETE`, exit 0. |

**Degraded but not incorrect — accept and document, do not "fix":**

`_report_from_checkpoint` deliberately sets `registry_version`, `profile_id`,
`profile_hash` to the literal `"resume"`, and zeroes `outcome_counts`, `role_counts`,
`location_counts`, `detail_fetch_count`, `detail_failure_count`. These flow into
`ScanMetrics` (1209-1226), so a resume's metrics show `successful_company_count=0`,
`attempted_company_count=0`, `role_candidate_count=0`. That is *honest* — the run
contacted no sources — and its docstring says so explicitly. It is only misleading once
(f) writes it over a real scan's report, which is why fixing (f) is what matters here.

**Conclusion, corrected:** the *report-consumer* audit found nothing beyond (e), (f), (g)
— every field of `FilterVerificationReport` is either correctly populated or correctly
degraded once it reaches an existing code path. But that scope was too narrow: it audited
what the checkpoint path *produces into the existing pipeline*, not what the *new,
not-yet-built* `evaluate` command must additionally do that `run_scan`/
`resume_from_checkpoint` get for free today. 1.3e below is that second pass, done after a
dedicated stress-test review, and it finds two real gaps. The three defects (e)(f)(g)
still share one root cause — **`process_filter_report` and its callers were written for
`collect_listings` output and assume a report always describes a set of contacted
companies** — but (h) and (i) below have a different root cause: they are safety
properties the *existing* commands get implicitly from code `evaluate` does not share.

### 1.3e ⚠ Two gaps found in stress-testing (2026-10-01) — safety properties `evaluate` does not inherit

**(h) `evaluate` needs `ScanLock`, and nothing in the proposal says so.** `ScanLock`
(`persistence/locking.py`) is acquired inside `run_scan` and `resume_from_checkpoint`
(`scan.py:277`, `scan.py:396`) for the whole pipeline run — it is invisible to `cli.py`,
which never references it directly. The lock is what stops a scan and a resume from
touching `state/jobs.sqlite3` at the same time today. §1.3(c) specifies `evaluate` as a
new CLI command wrapping `process_filter_report`, but says nothing about acquiring
`ScanLock` around it. Without it, nothing prevents `evaluate` from running concurrently
with a live `scan` — both writing verdicts and `observe_listing` state to the same
database at once. **Required:** `evaluate` must take `lock_path` and wrap its body in
`ScanLock(lock_path)` exactly as `run_scan`/`resume_from_checkpoint` do; add to 1.9's
build order and to the test list in step 2 ("`evaluate` refuses to start while `ScanLock`
is held by a live scan").

**(i) `assert_resumable` has no migration-version guard.** It checks staleness (24h) and
three string fields — `profile_version`, `prompt_version`, `model_policy`
(`checkpoint.py:184-190`) — against the live config. It does **not** check the checkpoint
against `persistence/database.py`'s `schema_migrations` table. If a schema migration
lands between a checkpoint's write and a later `evaluate`/`--resume` reading it — e.g. a
new NOT NULL column — `migrated_database` applies the migration on open regardless, and
whatever `process_filter_report` then writes through the repository either hits a hard
constraint violation (best case: loud failure) or silently takes a default for a column
the checkpoint's data never populated (worse: a valid-looking but wrong row). This is a
narrower window than the config-version guard already covers, but it is the same failure
shape — one report mixing data written under two different schemas — and the existing
guard does not catch it. **Required:** either record the schema version in the checkpoint
at write time and compare it in `assert_resumable`, or document explicitly that
`evaluate`/`--resume` must not be run across a migration and accept the risk. Silence is
not a valid third option, since it is exactly the kind of gap the 24h staleness and
version guards exist to close for the other three fields.

Neither (h) nor (i) is hypothetical risk-stacking — both are gaps in a proposal that
otherwise goes out of its way to guard against exactly this class of problem (stale
checkpoints, mismatched config versions, concurrent writers via `ScanLock` on the
existing paths). Folded into step 2 of 1.9, in the same commit as (a)-(d), since
`evaluate` doesn't exist yet to retrofit onto later.

### 1.3a Why this is the right call, stated plainly

I initially proposed the SQLite version and was wrong. The error was inferring from column
names that `jobs` nearly had what evaluation needs. Reading `CheckpointRow`
(`checkpoint.py:55-73`) — the authoritative statement of what the stage consumes — shows
it needs `company_id`, `title_original`, `location_original`, `canonical_url`,
`candidate_section`, a full `RoleFilterResult`, an optional `LocationFilterResult`, and a
complete 12-field `NormalizedJob`.

`jobs` has four of those. The rest would be eight-plus new columns, including two that
cannot be recomputed:

- **`candidate_section`** (strict_recent vs uncertain_date) comes from recency assessment
  during collection. The checkpoint docstring already warns that guessing it *"would
  silently move jobs between sections."*
- **`LocationFilterResult`** for Workday-style sources came from a *detail fetch* during
  the filter phase. That is why stage 2 does network I/O at all; it is not a pure function
  of stored data.
- **`date_basis`** is the tell. The column exists on `jobs` (§3.5 required it, "can't be
  added retroactively") and is **NULL on all 3,677 rows** — verified 2026-10-01. The
  schema-migration path would have been adding more columns of exactly this kind to a
  table that is already not populating the ones it has.

`RoleFilterResult` is the one genuinely recomputable piece — `filter_role(title, profile=)`
is pure over the title — but recomputing one field does not justify persisting the other
seven.

### 1.3b The honest cost of this choice

A checkpoint file is a second store that can disagree with `jobs`. This is a real
liability and the strongest argument for the SQLite version. It is acceptable here
because:

- The checkpoint is **derived, never authoritative**. `jobs` remains the source of truth
  for verdicts, lifecycle, and dedup; `evaluate` re-checks `_needs_processing` against the
  live DB on every row, so a stale checkpoint can cause redundant work but cannot corrupt
  state.
- `assert_resumable` already refuses a checkpoint whose `profile_version`,
  `prompt_version`, or `model_policy` disagrees with the current config.
- The staleness window bounds the disagreement (1.5).

The cost that does *not* go away: the checkpoint is **per-run**, covering only the most
recent scan's retained set. Combined with 1.4b (no re-judging through `evaluate`), this
means the design deliberately supports *one* operation — finish the current run's
outstanding work — and nothing else. Archival re-analysis across past corpora is out of
reach; if that need ever appears, it is the trigger to revisit the SQLite version, with
the full column cost from 1.3a understood.

### 1.4 Recovering the 3,026 already-stranded rows

⚠ **This proposal does not rescue them.** Worth stating plainly, because an earlier draft
of this section claimed it did.

No checkpoint exists for the 2026-09-30 run — it completed, so `scan.py:809-810` deleted
it. The changes in 1.3 are forward-looking: they make the *next* run's retained set
re-evaluable. They cannot reconstruct a checkpoint that was never kept.

`reports/latest_scan.json` → `review_candidates` does cover the stranded rows by
`canonical_url` (**3,026/3,026** failed, **392/392** pending, verified 2026-10-01), but it
carries only `title`, `location`, `company_name`, `candidate_section`, `category`,
`reason`, and `evidence` — **not** `RoleFilterResult`, not `LocationFilterResult`, and not
a `NormalizedJob`. A checkpoint cannot be synthesized from it without inventing filter
decisions, which is precisely the "guessing silently moves jobs between sections" failure
the design warns about.

**So the recovery plan is: run one more full scan.** It costs the 3.5h collection tax one
final time. On that run, `_needs_processing` automatically retries all 3,026 + 392 rows
(the `"limit reached"` match at `scan.py:876-880`), the 259 completed rows hit cache, and
— with 1.3 shipped — the run leaves behind a durable checkpoint so this is the *last* time
the tax is paid.

**Sequencing: ship 1.3 before that scan, not after.** Shipping after wastes the run.

### 1.4d ⚠ The 3,677 / $7.23 estimates do not survive a state reset

Relevant only if `state/jobs.sqlite3` is ever cleared — but the §4.3 wipe is still a
planned step, so record it now.

`collect_listings` consults `first_seen_lookup` per job (`collection.py:419-431`). When a
source does not verify publication dates, the stored `first_seen_at` is used as the
recency basis and the row lands in `CandidateSection.UNCERTAIN`; jobs whose stored
first-seen has aged past the window drop out entirely.

**Clear the database and that history is gone.** Every such job re-enters as newly seen,
so rows that previously aged out become retained again — pushing the retained count up by
an unknown amount, and the token and dollar estimates with it. The measured 3,677 jobs /
~28.9M tokens / $7.23 describe one run against populated history; they are a measurement,
not a forecast.

Worse, the first post-reset scan **cannot reconstruct what it destroyed**: it establishes
a new first-seen baseline dated today, but it has no way to learn when those postings were
actually published. Recency filtering is therefore degraded for one full window
(`recency_window_days`) afterward, and `days_active` (§4.2a) is wrong for every
pre-existing job.

⚠ **Correction: 3,677 is not a floor either.** An earlier draft of this section said a
post-reset scan could only retain *more*. That is wrong in both directions — sources are
added and removed, boards change size, postings close, and adapters break. 3,677 is one
measurement of one run against one registry state, and the only honest statement is that
a post-reset retained count is **unpredictable**, not bounded below.

The same applies to the caps: **47M tokens is measured headroom for that run, not a
guarantee for any other.** It is ~1.6× a specific observation, which is prudent sizing,
not a proof.

**Consequences:**
- Do not size budget caps for a post-reset scan from the 3,677 figure, and do not treat
  the §1.4a caps as proof a reset run cannot halt. They are sized on one prior run.
- **The two plans are mutually exclusive and must not be run together.** 1.4 and build
  step 4 recover the existing 3,026 + 392 rows *in place*, which depends on the very
  `evaluation_status` and `first_seen_at` history a reset destroys. If state is cleared,
  there is nothing to recover: those rows cease to exist, `_needs_processing` has no
  input, and the recovery narrative simply does not apply. Pick one path explicitly —
  **recover-in-place (recommended, per this section) or reset-and-rebaseline** — and
  ignore the other's steps entirely.
- The §4.3 wipe should be scheduled deliberately, with the one-window degradation
  accepted explicitly — not folded into a recovery run as a convenience.
- **The current 3,677-row corpus is worth more than it looks**, because it carries
  first-seen history that cannot be recreated. Prefer recovering it in place (1.4) over
  any reset.

### 1.4a Verify the budget caps first

Non-negotiable precondition for that run. The 2026-09-30 failure was a 1M-token cap
halting evaluation 140 jobs in. `.env` should carry
`JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS=47000000`,
`JOB_FINDER_LLM_MAX_REQUESTS=7000`, and `JOB_FINDER_LLM_MAX_OUTPUT_TOKENS=2000000`
(sized ~1.6× measured need: 28.9M / 4,045 / 1.21M). Caps are **per-invocation**, rebuilt
in `cli.py`. Check before launching, or the 3.5 hours are spent to reproduce the same
halt.

### 1.4b `evaluate` is recovery-only — ✅ DECIDED 2026-10-01

> **Decision: `evaluate` keeps `assert_resumable`'s version guard unchanged. No
> `--reevaluate` flag. Any prompt, profile, or model change requires a full `scan`.**

The question was whether `evaluate` should be allowed to bypass the guard:

```
if was != now for (profile_version, prompt_version, model_policy):
    raise CheckpointError("configuration changed … run a full scan")
```

**Rejected.** The guard's docstring reasoning holds — *"resuming would produce one report
containing two incompatible sets of judgements, which is worse than re-scanning"* — and a
bypass would have made `evaluate` two tools wearing one name: a safe recovery path and a
destructive re-judge path, distinguished only by a flag. The destructive one costs a full
LLM pass (~$7.23) anyway, so it saves only collection time while introducing the one way
this command could ruin good data.

**Consequences, accepted deliberately:**

- `evaluate` does exactly one thing: finish work the current configuration has not
  finished. Its contract is "rows where `_needs_processing` holds, under the *same*
  judgement rules." That is a sentence with no caveats, which is the point.
- A prompt or model change means a full `scan`. Correct: those changes invalidate every
  cache entry by design, so the LLM cost is identical either way, and the scan also
  refreshes listings that may have closed since the checkpoint.
- `evaluate` therefore **cannot** corrupt a report by mixing judgement rules. The failure
  mode is eliminated structurally rather than guarded by a flag.
- This shrinks the claimed benefit — see the correction in 1.6. `evaluate` is a recovery
  tool, not a prompt-iteration tool. That is the honest scope.

**Implication for the build:** nothing in `assert_resumable` changes. `evaluate` calls it
exactly as `resume_from_checkpoint` does today, and a version mismatch produces its
existing, already-correct error telling the operator to run a full scan.

### 1.4c Descriptions in the checkpoint are only the inline ones

A refinement to 1.3 that changes expected behaviour. `_write_resume_checkpoint` snapshots
`filtered` — the deterministic filter's output, captured **before** `_ensure_description`
runs. So the checkpoint carries a description only where the *adapter* supplied one at
list time.

Measured from `config/company_sources.json` (enabled sources only):

| `detail_strategy` | enabled sources |
|---|---|
| `listing_payload` (description inline) | **92** |
| `detail_endpoint` | 41 |
| `detail_page` | 17 |

So descriptions for the ~58 detail-fetching sources are **re-fetched on every
`evaluate`** — they were never in the checkpoint to begin with. Consequences:

- `evaluate` is not network-free. Budget roughly the 2,447 detail fetches the last run
  made, minus whatever has closed.
- A source that has since started 403-ing sends its rows to `description_unavailable`
  rather than to the model. The `description_hash` cache absorbs repeats, so cost is
  bounded, but coverage is not guaranteed identical to the original run.
- The 85 MB size estimate in 1.3 is therefore an **upper bound** that assumes every row
  carries text; the real file will be smaller. Measure it on the first run rather than
  designing around the estimate.

### 1.5 Staleness policy

A stored listing decays: a job can close between collection and a later evaluation pass.
`checkpoint.py` already answers this with `STALENESS_LIMIT` and `assert_resumable`; reuse
them rather than inventing a second policy.

- The existing 24h `STALENESS_LIMIT` applies unchanged, with **no override flag**. The
  override existed in earlier drafts only to serve prompt iteration, which 1.4b removed;
  with `evaluate` scoped to recovery, a >24h gap genuinely does mean postings may have
  closed, and a full scan is the correct answer. One fewer flag, one fewer way to get a
  stale report.
- `evaluate` never runs lifecycle/absence detection — it is not a scan and does not
  observe the full listing set. This is the same reasoning `resume_from_checkpoint`
  already documents.
- The existing cache key (`description_hash` + `profile_version` + `prompt_version` +
  `model_policy`) is unchanged, so a config change still correctly invalidates.

### 1.6 What this is worth — scoped honestly after 1.4b

⚠ Earlier drafts of this section claimed the main prize was cheap prompt iteration. **That
claim is withdrawn.** 1.4b rules out re-judging under a changed prompt via `evaluate`, and
the cache key includes `prompt_version`, so a prompt change costs a full LLM pass
regardless. Prompt iteration remains a full-`scan` activity.

What the change actually buys, in order of value:

**1. Interrupted or failed evaluation stops costing 3.5 hours.** This is the whole
benefit, and it is sufficient on its own. The 2026-09-30 history — five `KeyboardInterrupt`
runs and a budget halt that stranded 3,026 rows — is entirely made of this failure mode.
Evaluation is the long, fragile, network-and-API-dependent stage; collection is the
expensive one. Today a fault in the former forces a rerun of the latter, and that coupling
is the defect.

**2. The retry path stops being theoretical.** `_needs_processing` already knows how to
recover budget-exhausted and provider-failed rows, but today it can only run inside a full
scan, so a recorded-and-recoverable failure sits recoverable-in-principle for days. A
command that invokes it makes the existing recovery logic reachable.

**3. It makes the eval-set work practical later, indirectly.** The 20-case relevance set
(`config/relevance_evaluation_set.json`) is inert — `tests/matching/test_relevance_set.py`
asserts things about the JSON's shape and never runs it against a model, so relevance has
no accuracy gate (unlike seniority's 90% gate). That work needs a stable corpus with
verdicts; this change is what gets the corpus fully judged in the first place. It is a
precondition, not a mechanism.

**What it is explicitly not:** a way to re-judge, A/B prompts, or iterate cheaply on the
LLM layer. Those remain full-`scan` operations by decision, not by oversight.

### 1.7 Rejected alternatives

**Move the work queue into SQLite (add `title`/`location`/… to `jobs`, add
`job_finder evaluate` reading from the table).** Rejected — see 1.3a. Attractive because
`jobs` is already the source of truth for dedup and lifecycle, and it would make
re-evaluation corpus-wide rather than per-run. But it needs eight-plus new columns, two of
which (`candidate_section`, detail-fetched `LocationFilterResult`) cannot be recomputed
from stored data, and it would extend a table that is already failing to populate
`date_basis` on any of its 3,677 rows. The gain over a durable checkpoint is archival
re-analysis, which nothing currently needs. Revisit only if that need appears.

**Persist `FilterVerificationReport` wholesale and add `--from-filter-report <path>`.**
Rejected for a different reason than the above: the full report is ~2 MB of listing
records including all 42,116 rejected rows, and its schema is coupled to reporting
concerns that change independently of evaluation. `CheckpointRow` exists precisely because
someone already worked this out — its docstring says it is *"a deliberately reduced form
of `FilterListingRecord`… Keeping it minimal means a schema change to the filter report
does not silently invalidate checkpoints."* Reuse that, don't re-litigate it.

**Generalised per-stage checkpointing for all three stages.** Symmetric and tidy, and
solving a problem the failure history does not show. Collection is already resilient per
company (`failed_company_count: 3` on the last run, which carried on fine). There is one
seam that matters; build one.

### 1.8 Scope explicitly excluded

- **Storing descriptions in SQLite** — settled, do not reopen. Note this is *not* the same
  as the checkpoint, which does and must carry the ones it has (1.3, 1.4c). "Re-fetch is
  cheap" holds for the 67% of rows that needed a detail fetch anyway; for the other 33% it
  manufactures a request that can fail.
- **Parallelising evaluation** — `candidate_evaluation` still has no `seconds=`
  instrumentation, unlike collection and filter. Three prior performance diagnoses here
  were wrong because the timing data did not exist. **Measure first**; that measurement is
  a reasonable companion task to this work but not part of it.
- **Any change to the deterministic filter or title blocklist** — settled, validated at
  0 false negatives, out of scope.

### 1.9 Build order

0. 🔴 **Fix (j) — `scan` raises `TypeError` before collection** (1.3f). Every plain scan
   is broken today; `--resume` is the only working path, which is why the breakage went
   unnoticed. Nothing below can be verified until this lands. Add the CLI-level smoke
   test in the same change — the untested `cli.py`↔`scan.py` seam is what allowed an
   arity mismatch to ship.
1. **Fix (e), (f) and (g) as standalone bugs** (1.3c). All live in `--resume` today: it
   deletes its own checkpoint, overwrites `reports/latest_scan.json` with a company-less
   partial report, and reports `completed` / exit 0 even when it halts on budget.
   **(g) is the priority**, and the fix is the two-axis outcome model in 1.3c — *not*
   making `healthy` reject zero companies, which would report a successful `evaluate` as
   `FAILED`. Note (g)'s scan-side twin: a `scan` that halts on budget also reports
   `COMPLETE`. Also add a clear error (not a bare `KeyError`) when a checkpoint references
   a `company_id` since deleted from the registry.
2. **Verify the `.env` budget caps** (1.4a), and do **not** size them from the 3,677
   figure if any state reset is planned (1.4d).
3. **Ship 1.3 (a)–(d), plus (h), (i) and (k)** — move the checkpoint write, make its
   retention conditional on retryable work (b), add `evaluate`, guard the
   `observe_listing` side effects (d), wrap `evaluate` in `ScanLock` (h), resolve the
   migration-version gap (i), and make observation **insert-if-absent** so an empty DB
   still works (k). (d), (h) and (k) are not optional: without (d) `evaluate` corrupts
   lifecycle data, without (h) it can race a live scan, without (k) it cannot recover the
   crash-early case it exists for. Tests:
   - a run with retryable work left behind keeps its checkpoint; a fully judged run
     deletes it
   - `evaluate` skips rows already `completed`
   - `evaluate` leaves `last_seen_at`, `sighting_count` and `consecutive_absences`
     byte-identical for every **existing** row
   - `evaluate` against an **empty** `jobs` table evaluates every checkpoint row, with
     `first_seen_at == last_seen_at == checkpoint.scan_at` (k)
   - a checkpoint round-trips descriptions for inline-description rows without issuing
     an HTTP request
   - `evaluate` **refuses** a version-mismatched checkpoint, pointing the operator at a
     full scan (1.4b — no override exists, and the test is what keeps it that way)
   - `evaluate` **refuses to start while `ScanLock` is held** by a live scan (h)
   - (i) resolved one way or the other — either a migration-mismatch test exists, or the
     risk is written down in 1.5 as an accepted gap
4. **Decide the feed question in 1.3c before or alongside this** — where recovered
   matches surface. Recommended: derive the feed from SQLite (`verdict` / `verdict_at`)
   and demote run reports to operational records. Until it is decided, `evaluate` output
   is operational only and is not the job feed.
5. **Run one full scan — recover-in-place path.** Pays the 3.5h collection tax; the
   existing 3,026 + 392 are retried automatically by `_needs_processing`; the checkpoint
   survives only if work remains.

   ⚠ **This step assumes state is NOT cleared.** If you choose the reset path instead
   (1.4d), delete this step and step 6's recovery framing: after a reset those rows do not
   exist, nothing is recovered, and the scan simply establishes a new baseline with
   degraded recency for one window. **The two paths are mutually exclusive — do not run
   both.**
6. **Confirm against the acceptance criterion** (1.3c): *every retained row ends in
   exactly one of — a verdict, a recorded terminal reason, or an accurately reported
   unfinished state.* Also check the terminal-review rate: a large `manual_review` share
   means the prompt or schema broke, and is not a "complete" run in any useful sense.

   Do **not** use the old DB-wide `completed ≈ 3,677` check — the retained set varies
   between runs, so it is not what any run promises. Equally, do not read the run's
   `evaluated=N` progress line as corpus state.
7. **Then** the relevance accuracy gate becomes practical (1.6, §3).

---

## 2. Known-latent issues

Real but not urgent. Mirrored in `CLAUDE.md` so they are not rediscovered as new findings.

- **`merged_evaluator.py` dropped every `maxLength`** that `seniority.py:62-68` declares.
  Unbounded strings reach SQLite and markdown reports. Measured against 259 real
  responses: max evidence 259 chars against a 500 cap, zero violations. **Do not raise
  again without new evidence.**
- **One bad evidence field discards all three judgments**, contradicting 2.5's stated goal
  of per-judgment diagnosability.
- **Retry resends a byte-identical request** with no error feedback, and sets no
  temperature or seed.
- **`is_confident_rejection` is defined and tested but never called** —
  `merged_prompt.py:73` implements it; `scan.py` reimplements the rule inline, in a
  different order.
- **The relevance eval set is inert** — see 1.6. No accuracy gate on relevance, unlike
  the seniority path's 90% gate.
- **`max_workers` is effectively dead code** — `ThreadPoolExecutor` is wired in
  `collection.py:329`, but the parameter defaults to 1, nothing passes it, and there is no
  CLI flag. Collection is single-threaded in practice.
- **Amazon geo filter** (`amazon_jobs.py:354`) still `raise`s on `country_code != "IND"`,
  and the caller books it as a `malformed_job` diagnostic — miscategorising a filtered job
  as corrupt source data, polluting the signal that says an adapter broke. The decision to
  keep the filter stands; expressing the rejection as a counted filter decision rather
  than a `malformed_job` remains worth doing opportunistically.

---

## 3. Explicitly deferred

- **Eval set extension / relevance accuracy gate** — trigger: §1 landing, which makes
  cheap repeated evaluation possible.
- **Evaluation-phase timing instrumentation** — trigger: before any attempt to speed
  evaluation up. Measure before optimising.
- **Website schema** — wait until the scanner's output shape settles.
- **180-company backlog** — 174 of 180 are `search_only` (no adapter exists yet), so this
  is adapter-*writing*, not refactoring. Trigger: a clean, stable full scan — which today
  means §1 landing and a run where the retained set actually gets verdicts.
- **Large `list_jobs` template-method rewrite** — deferred until the adapter shape has
  stabilised across a wider sample; writing backlog adapters against `_support.py` is what
  reveals which abstractions generalise.
- **Model choice** — staying on the configured `gpt-5.6-luna`. Revisit with the eval set,
  not before.
- **Repost tracking** — dropped; retroactively computable if it ever matters.
