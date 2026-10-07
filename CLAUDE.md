# JOB_Finder — orientation for AI assistants

India AI/ML job scanner. Scrapes ~150 company career sites, filters deterministically,
then asks an LLM to judge the survivors.

**Read this file first. It exists so you don't rediscover the same facts by grepping.**
Then read **`docs/decisions.md`** before proposing any change — several obvious-looking
optimisations there were measured and rejected, and re-proposing them wastes your budget
and, in one case, would break the system.

**Do not read `docs/archive/`, `docs/reviews/`, or `reports/`.** They are denied in
`.claude/settings.json`. The archive describes filters and an LLM call that no longer
exist; `reports/` is 42MB of generated output. Nothing in them is needed to work on the
code, and `latest_scan.json` is better queried with `jq` than read.

## Don't burn tokens on these — the answers are here

| Question | Answer |
|---|---|
| Is the scan parallel? | **No.** Single-threaded everywhere. `max_workers` exists in `collection.py` but is **dead code** — defaults to 1, nothing passes it, no CLI flag. |
| Are LLM calls batched? | **No.** One job per call, sequential, with one validation retry. Discovery saves the entire retained batch first; an unchanged completed judgment can be reused without a call. The historical full run retained 3,677 jobs. |
| Where are descriptions stored? | Full retained descriptions are frozen in **`batch_candidates.payload_json`** before evaluation. Completed evaluations also write **`jobs.description`**. Rejected listing descriptions are not saved in the batch. |
| Is relevance evidence stored? | **Yes**, since migration 5: `relevance_evidence`/`relevance_reason` and the conditional `location_evidence`/`location_reason`. Rows judged before it keep NULLs — the text is gone and cannot be backfilled. |
| What does a run cost? | Historical estimate: **$0.0020/job**, ~$7.23 for 3,677 jobs at the then-configured rates. Current usage/rates are recorded per request in SQLite and exported to `state/llm_costs.jsonl`; view with `job-finder costs`. Unknown usage stays unknown; discarded spending stays in totals. |
| Why is `conditional_pass` ~94%? | **By design, not a leak.** `filter_role` returns `CONDITIONAL_DESCRIPTION` for every surviving title — `EXPLICIT_PASS` exists in the enum but is unreachable, so nothing skips the LLM gate. See "Settled decisions". |
| Where does time go? | Unmeasured. `candidate_evaluation` has **no `seconds=` instrumentation**, unlike collection/filter. Measure before optimising. |
| Does anything prune the DB? | `state prune` manually clears descriptions not seen in 90 days, protecting fresh batch candidates, and removes an expired batch. It preserves job rows/first-seen dates and spending. Fresh scans replace the singleton batch; daily lifecycle baselines/counts are bounded on publication. Judgment cache, request accounting, old reports/logs and historical `scan_runs` have no automatic retention deadline. |
| Is `jobs.date_basis` used? | **No — dead schema.** Migration 4 adds the column; `JobRecord` has no such field and no statement reads or writes it. |
| Is the DB in WAL mode? | **No.** `database.py` sets `foreign_keys` and `busy_timeout` only, so it runs in rollback-journal mode. |
| Do `reasoning_effort`, `temperature` or `seed` stabilise Luna? | **No — measured.** The gateway accepts all three; none reduced rerun instability (luna flips relevance on ~26% of hard cases with prompt 1.1.0). Neither did evidence-before-verdict schema order. Only prompt clarity helped (1.2.0: 14%). See `experiments/llm_compare/README.md`. |
| Why was the review list ~1,000 rows? | **Not the LLM.** On 2026-10-02, 816 of 1,060 were Bank of America `detail_location_unavailable`: Workday echoed the site as `Lateral-US` vs configured `lateral-us`, and a case-sensitive URL check failed every detail fetch (fixed in `workday.py`). Most of the rest were location reviews and empty-description rows, now judged by the model. |
| Is Sol (gpt-6.1-sol) ground truth for Luna? | **No.** On 72 hand-adjudicated disagreements, with prompt 1.1.0 Sol missed 9 relevant jobs and passed 13 irrelevant ones. With 1.2.0 Sol improved too and is still better than Luna (per call: Sol 0 missed / 3 extra, Luna 0.3 / 6) at ~12x the cost. On the fresh 2026-10-03 batch Luna 1.2.0's errors were mostly repeatable (same answer every rerun), i.e. prompt gaps; 1.3.0 closed most of them. Adjudicate from the description; verdicts are in `experiments/llm_compare/lab/adjudicated_cases.json` and `truth_2026-10-03.json`. |
| Which prompt and effort does production use, and why? | **Prompt 2.0.0 at Luna `high`** (`JOB_FINDER_LLM_REASONING_EFFORT=high`), chosen on a blind 1,000-job benchmark labelled under `experiments/llm_compare/policy/policy_v1.md` and reviewed by the user. Per call over 966 scored jobs: shown jobs missed 8.4 → 2.0 vs 1.3.0, at ~14 → ~22 extras. Effort helps only with a clear prompt (it did nothing for 1.3.0). Higher effort is ~1.5x slower per call. Details: `experiments/llm_compare/bench_2026-10-05_report.md`. |
| Does the second opinion (`JOB_FINDER_LLM_SECOND_OPINION`) fix Luna's errors? | **Only the unstable ones.** It votes away answers that flip between reruns (~2% of jobs). An error Luna makes on every call survives any vote; fix those in the prompt and measure with `experiments/llm_compare/lab`. |

## Architecture: discovery checkpoint, then evaluation, one lock

1. **`source_collection`** — `collection.py`, scrapes ~150 companies. ~3.5h.
2. **`deterministic_filter`** — same file. Also does network I/O (Workday listings say
   "N Locations", so each needs a detail fetch). Adobe alone is ~190 requests.
3. **`description_collection`** — `daily_scan.py:_publish`. Retrieve full descriptions
   for every retained identity, including jobs with a previous cached judgment. Save the
   complete batch, coverage and daily lifecycle changes in one SQLite transaction.
4. **`candidate_evaluation`** — `daily_scan.py:_evaluate`. Use the frozen descriptions;
   reuse an exact-request judgment or make one merged LLM call per job. Persist replies
   before validation and commit complete judgments plus progress atomically.

`scan` runs both stages. `scan --discovery-only` stops after publishing full descriptions,
coverage and lifecycle, before any LLM calls or cache reuse. It leaves all retained candidates
pending; successful discovery returns coverage status 0/2 and reports evaluation as deferred.
The normal evaluation configuration is still loaded and the midnight deadline still applies.
`evaluate` resumes pending candidates without source/detail
requests; completed evaluation regenerates cumulative reports without LLM calls.
`force_reevaluate` creates a new attempt for the entire saved batch, bypassing the
judgment cache; `evaluate` resumes that attempt if interrupted. All three commands,
their dated logs/reports and accounting export share `ScanLock`.

Admission uses the date when the command starts in **IST (UTC+05:30)**. A batch admitted
at 21:00 allows new evaluation invocations until midnight, not for a sliding 24 hours.
An already admitted command may finish after midnight. Fresh scan discards the previous
batch immediately. Fatal failure before publication requires a fresh scan; after
publication, evaluation/report failures preserve the batch. A failed individual source
does not cancel healthy-source coverage; zero successful/valid-empty sources is fatal.

Funnel from the 2026-09-30 run: 42,116 listings → 21,963 recent → 17,555 role → **3,677
retained** → LLM. Of 259 evaluated: 83 substantive, 23 peripheral, 153 unrelated (59%
rejected — the gate earns its keep).

## The merged LLM call (`to_change.md` 2.5)

`MergedEvaluator` makes one call per job (prompt schema 2, `config/merged_prompt.toml`)
returning a one-sentence `work_summary` first, then three judgments: relevance
(`core_ai`/`ai_involved`/`uncertain`/`not_ai`; only `not_ai` hides, `uncertain` is shown
last and tagged), seniority (`true`/`false`/`"uncertain"`), and `location_fit`
(`india`/`open_remote`/`relocation`/`excluded`/`uncertain`) **only** when the deterministic
filter couldn't resolve it. `excluded` hides; `relocation` and `uncertain` go to the review
list unless seniority is already `false`. Rows judged under 1.x keep
`substantive`/`peripheral`/`unrelated` in `jobs.verdict`; schema-1 prompts are refused.

Admission to evaluation is filter outcome RETAINED **or REVIEW** (role passed, location
unresolved). Until 2026-10-03 REVIEW rows went straight to the review list, so the location
judgment never ran and unresolved rows were never relevance-checked; on the 2026-10-02
batch 48 of 51 such rows were unrelated. A posting with no description is judged from its
title (`daily_scan.NO_DESCRIPTION` placeholder) instead of being sent to review; the
placeholder is part of the cache key, so a later real description re-judges the job.

Each judgment carries a **verbatim evidence quote**, validated as a substring of
title+description after whitespace/case/typography normalization (dash and quote variants,
non-breaking spaces, a trailing period or leading bullet). Failures trigger the retry
(~1% of calls with prompt 1.2.0).

Prompt 2.0.0's relevance boundary is the user's written policy
(`experiments/llm_compare/policy/policy_v1.md`, v1.2), not wording to tidy: the title alone
can show a job, testing or securing AI systems counts, using AI tools does not, AI sales
and CRM-practice consulting are hidden. Its text is byte-identical to the benchmarked lab
prompt; change it only after re-running `experiments/llm_compare/run_bench_2026-10-05.sh`
style scoring against `lab/truth_bench_2026-10-05.json` (score the tuning half, look at
the sealed test half once). A tempting one-line fix (prompt v11) cost a real miss. `seniority_match` is `bool | str` — **never truthiness-check it**;
`"uncertain"` is truthy. All current consumers correctly use `is True` / `is False`.

Cache key: SHA-256 of the **exact rendered LLM request plus model policy**, including
title, description, seniority target, conditional location, prompt/schema and output
limit. Cache entries contain the complete merged judgment, including rejections.
Legacy description/version-only decisions cannot prove that fingerprint and cause a
one-time cache miss. Changes to evaluation rules require `force_reevaluate` or a fresh
scan; source/discovery filter changes require a fresh scan even for forced evaluation.

## Where description text lives (and for how long)

- Many adapters (Greenhouse, Lever — ~34 files) populate `description` **at listing time**,
  not at detail-fetch time. Workday-style boards leave it `None` until `get_job_detail`.
- `FilterListingRecord.normalized_job` holds the whole `NormalizedJob` **by reference**, and
  a record is appended for **rejected** rows too. So `FilterVerificationReport.listings`
  pins every listing-time description for the entire ~3.5h run. This is the dominant
  memory cost of a scan and is **unmeasured**.
- On disk: SQLite holds full text in the current `batch_candidates` payloads and in
  completed `jobs.description` rows. Using the historical ~23kB average and 3,677
  candidates, description text alone is ~85MB per copy; retaining both can approach
  ~170MB, plus metadata, indexes and SQLite overhead. This is an estimate, not a new
  measurement. Memory still holds listing-time descriptions during discovery.
- The singleton batch remains physically stored after midnight but cannot be newly
  evaluated. A fresh scan, expired-batch prune or reset removes it. Completed job
  descriptions remain until changed, pruned or reset. SQLite backup/restore includes
  the batch and saved evaluation progress.
- Returned provider replies are temporarily stored in `llm_requests.response_json` for
  crash recovery, then cleared when a candidate completes or its attempt is discarded.
  Request IDs, usage, rates and discard reasons remain permanently. A crash during a
  provider call leaves unknown usage: replaying a saved reply is free, but repeating a
  call with no saved reply may incur another charge. Exactly-once provider billing is
  not guaranteed.

**Prune nulls the column; it must never delete the row.** `collection.py` reads
`jobs.first_seen_at` as the recency basis whenever a source lacks a verified publication
date. Delete a row and a still-live job looks newly-seen — it re-enters the funnel, is
re-evaluated at cost, and resurfaces as new. Deleting also bypasses
`MINIMUM_SIGHTINGS_TO_EXPIRE` and `COLLAPSE_RATIO` in `core/lifecycle.py`. Filter on
`last_seen_at`, never `first_seen_at`: a job first seen six months ago but still live every
week is exactly the row not to touch. Measured on 500 seeded jobs: 8.4MB reclaimed, all 500
rows and hashes intact.

## Settled decisions — do not re-propose (full reasoning in `docs/decisions.md`)

- **Description trimming: rejected.** Saves ~$4/scan, discards ~83% of text. Seniority
  signal is often back-loaded, and trimming away a quotable sentence breaks evidence
  validation, causing retries. User explicitly said skip.
- **Tightening the title filter: rejected.** Change 2.2a deliberately widened it from 11%
  to ~70-79% pass, validated at **0 false negatives** over 1,300 Amazon + 1,120 Greenhouse
  + 77 hand-written titles. The old narrow filter silently dropped real jobs
  (`ML Engineer, Prime Video Ads CX` blocked on "pr" inside *Prime*). Tightening
  re-introduces exactly those. If output volume is the complaint, tier the report instead.
- **Schema `maxLength` bounds, prompt-injection hardening, retry rework: deferred.**
  Real but latent. Measured against 259 real responses: max evidence 259 chars vs a
  500 cap, zero violations. Don't raise these again without new evidence.

## Known-latent issues (documented, not urgent)

- `merged_evaluator.py` schema dropped every `maxLength` that `seniority.py:62-68` has.
  Unbounded strings reach SQLite and markdown reports. No real response has approached it.
- One bad evidence field discards **all three** judgments, contradicting the module's own
  stated goal of per-judgment diagnosability.
- Retry resends a byte-identical request with no error feedback; no temperature/seed set.
- `is_confident_rejection` is defined and tested but legacy `scan.py` helpers
  reimplement the rule inline. The daily CLI persists/reuses full judgments.
- The 20-case relevance eval set is **inert**: tests assert things about the JSON file,
  never run it against a model. No accuracy gate, unlike the seniority path's 90% gate.

## Working agreements

- **Verify before claiming.** This codebase has repeatedly punished inference from metric
  names. Read the code or query the DB; don't reason from a number's name.
- **Measure before optimising.** Three separate performance diagnoses here were wrong
  because the timing data didn't exist.
- **Never record a transient condition as per-job state.** Budget exhaustion was once
  written as `invalid_seniority_output`, which made 3,026 rows permanently unretryable.
  If a status means "we didn't get to it", it must differ from "we judged it and failed".
- Commit in focused increments with real reasoning in the message, not just what changed.
- Prefer stdlib. No `rich`/`tqdm` — `terminal.py` uses raw ANSI deliberately.

## Commands

```bash
python -m pytest -q                      # full suite, ~25s (1000+ tests)
python -m ruff format src/ tests/ && python -m ruff check src/ tests/
python -m mypy src/

python -m job_finder scan --min-request-interval 0.15 --max-concurrent-per-host 2
python -m job_finder scan --discovery-only # save full batch/descriptions; no LLM calls
python -m job_finder evaluate            # resume saved attempt before midnight IST
python -m job_finder force_reevaluate    # restart all saved candidates, paying again
python -m job_finder costs               # per-day spend, discarded totals, unknown usage
python experiments/llm_compare/lab/smoke_production.py  # one real call with production settings

# Reclaim disk by clearing description text for jobs not seen in 90 days. Keeps the rows.
python -m job_finder state prune --backup state/backups/pre-prune.sqlite3 \
    --confirm-database "$(python -c 'import pathlib;print(pathlib.Path("state/jobs.sqlite3").resolve())')"
```

**Never run the test suite while a scan is live** — tests write `state/` databases and
contend for `ScanLock`.

## Layout

`src/job_finder/`: `collection.py` (source/filter collection) · `daily_scan.py`
(canonical scan/evaluate CLI engine) · `daily_lifecycle.py` (same-date replacement) ·
`scan.py` (report records and legacy verification helpers) · `matching/` (LLM evaluators,
prompts and request journal) · `filters/` (`roles`, `locations`) · `persistence/`
(SQLite, batches and migrations) · `adapters/` (per-ATS scrapers, HTTP/connectivity) ·
`checkpoint.py` (legacy file helpers and listing codecs; retired from the daily CLI) ·
`cost.py`/`accounting.py` (permanent spending) · `terminal.py` (progress UI).

`experiments/llm_compare/` holds the Luna/Sol comparison harness, every prompt variant,
the adjudicated cases and the report; its run data is git-ignored.

Config in `config/`, state in `state/` (gitignored). Secrets in `.env` (gitignored —
**never commit**). `to_change.md` is the 986-line rewrite spec; sections are cited as
"2.5", "3.2" etc. throughout the code.
