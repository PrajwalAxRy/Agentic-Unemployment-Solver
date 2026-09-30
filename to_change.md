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

What remains is one architectural proposal (§1) and a short list of latent issues (§2)
that are real but not urgent.

---

## Index

**1. Decouple candidate evaluation from collection — PROPOSED, needs a decision**
- 1.1 The problem · 1.2 Why the checkpoint doesn't cover it · 1.3 The proposal
- 1.4 Migration and backfill · 1.5 Staleness policy · 1.6 What this unlocks
- 1.7 Rejected alternatives · 1.8 Scope explicitly excluded

**2. Known-latent issues** — documented, not urgent (mirrors `CLAUDE.md`)

**3. Explicitly deferred** — with triggers

---

## 1. Decouple candidate evaluation from collection — PROPOSED

> **Needs a decision before building.** Everything else in this file is either latent or
> deferred; this is the one live architectural question.

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

### 1.3 The proposal — make SQLite the evaluation queue

`jobs` is already nearly the right table. It holds `job_key`, `company_id`,
`canonical_url`, `evaluation_status`, `description_hash`, `last_seen_at`,
`profile_version`, `prompt_version`, `model_policy`, and the lifecycle columns. It is
already the source of truth for dedup and lifecycle. `_needs_processing` is already a
correct, exercised predicate for "this row still owes us a verdict."

Two columns are missing: **`title`** and **`location`**. That is the entire gap.

**Add:**

```sql
ALTER TABLE jobs ADD COLUMN title TEXT;
ALTER TABLE jobs ADD COLUMN location TEXT;
```

**Then add a command:**

```
job_finder evaluate [--limit N] [--company-id X] [--dry-run]
```

which selects rows where `_needs_processing` holds, rebuilds the minimal job record from
stored columns, re-fetches descriptions via `canonical_url`, and runs the existing
`process_filter_report` evaluation path — with `run_lifecycle=False`, since a partial
row set must never drive absence detection.

**Descriptions stay unstored.** Re-fetching is ~2,447 requests (measured), trivial next to
42,116-listing collection, and the fetch doubles as a liveness signal — a 404 during
evaluation is real information. This keeps the settled "don't store descriptions" decision
intact.

**`--resume` then becomes a special case of `evaluate`,** and `resume_checkpoint.json`
plus most of `checkpoint.py` can be retired. The change removes a special case rather
than adding one, which is the main argument for it.

### 1.4 Migration and backfill

The 3,677 existing rows would have `NULL` title/location after the migration, so
`evaluate` could not touch them without a backfill. **Verified 2026-10-01:**
`reports/latest_scan.json` → `review_candidates` contains 4,276 unique
`canonical_url` entries, each carrying `title` and `location`, and covers:

- **3,026 / 3,026** `failed` rows
- **392 / 392** `pending` rows
- 2 / 259 `completed` rows (irrelevant — they already have verdicts and hit cache)

So a one-shot backfill from the last report recovers the entire stranded set with no
re-scrape. Ship it as `job_finder state backfill-titles --report <path>`, idempotent,
matching on `canonical_url`.

After backfill, recovering the 3,026 + 392 costs ~$6.84 and roughly 30–40 minutes — versus
3.5 hours plus the same $6.84 today.

### 1.5 Staleness policy

A stored listing decays: a job can close between collection and a later evaluation pass.
The existing checkpoint answers this with a flat 24h cutoff; reuse the same idea rather
than inventing a second one.

- `evaluate` refuses rows whose `last_seen_at` is older than a configurable window
  (default 24h, `--max-age-hours` to override), printing the count it skipped.
- `evaluate` never runs lifecycle/absence detection — it is not a scan and does not
  observe the full listing set. This is the same reasoning `resume_from_checkpoint`
  already documents.
- The existing cache key (`description_hash` + `profile_version` + `prompt_version` +
  `model_policy`) is unchanged, so a config change still correctly invalidates.

### 1.6 What this unlocks — the actual reason to do it

Disaster recovery is the visible benefit; it is not the important one.

**The LLM layer becomes independently iterable.** Today, changing `merged_prompt.toml`,
`search_profile.toml`, or the model policy invalidates the whole cache *and* costs 3.5h
of re-scraping to see the result. With the seam, prompt iteration is a ~30-minute loop
against a fixed 3,677-row corpus. The LLM layer is the least-settled part of the system
and the one most likely to be touched again, so this tax is permanent, not transitional.

**It is the prerequisite for the accuracy gate.** The 20-case relevance eval set
(`config/relevance_evaluation_set.json`) is currently inert — `tests/matching/test_relevance_set.py`
asserts things about the JSON file's shape and never runs it against a model, so there is
no accuracy gate on the relevance path (unlike seniority). A stable, cheaply re-evaluable
corpus is what makes building that gate practical.

### 1.7 Rejected alternatives

**Persist `FilterVerificationReport` and add `--from-filter-report <path>`.** The obvious
fix, and weaker. It creates a second source of truth about job state sitting next to the
DB and free to disagree with it; it needs its own staleness policy and version guards,
duplicating what `checkpoint.py` already implements once. `checkpoint.py`'s own docstring
states the intended hierarchy: *"The checkpoint is a cache of work in progress, never a
source of truth."* Putting the queue in the DB honours that; a parallel report file
contradicts it.

**Generalised per-stage checkpointing for all three stages.** Symmetric and tidy, and
solving a problem the failure history does not show. Collection is already resilient per
company (`failed_company_count: 3` on the last run, which carried on fine). There is one
seam that matters; build one.

### 1.8 Scope explicitly excluded

- **Storing descriptions** — settled, and re-fetch is cheap. Do not reopen.
- **Parallelising evaluation** — `candidate_evaluation` still has no `seconds=`
  instrumentation, unlike collection and filter. Three prior performance diagnoses here
  were wrong because the timing data did not exist. **Measure first**; that measurement is
  a reasonable companion task to this work but not part of it.
- **Any change to the deterministic filter or title blocklist** — settled, validated at
  0 false negatives, out of scope.

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
