# Manual scan runbook

## Purpose

`job-finder scan` runs the complete discovery pipeline once. It reads public sources, applies the
rolling-ten-day, location, and title policies, suppresses previously processed jobs, then sends each
survivor to **one merged LLM call** that judges AI/ML relevance, seniority, and (only when the
deterministic filter could not resolve it) India eligibility. It writes local reports. It does not
schedule another run or send a notification.

Relevance is the consequential judgment: in the 2026-09-30 run it rejected **59%** of everything
that reached it. Expect a large share of evaluated jobs to come back `unrelated`; that is the gate
working, not a fault.

## Before the first run

1. Set up Python and dependencies as described in `docs/development.md`.
2. Configure the local `.env` variables listed in `docs/06_llm_provider_configuration.md`. Never
   paste the gateway key into chat or commit `.env`.
3. Verify the redacted provider connection:

   ```powershell
   uv run --locked job-finder check-llm
   ```

## Run the scan

From the repository root:

```powershell
uv run --locked job-finder scan
```

**Expect hours, not minutes.** The pipeline is single-threaded throughout. The 2026-09-30 run over
~150 sources spent roughly 3.5h on source collection, ~1h on the deterministic filter, then one
sequential HTTP fetch plus one LLM call per retained job — 3,677 of them. Keep the terminal open.

Useful flags:

```powershell
uv run --locked job-finder scan --min-request-interval 0.15 --max-concurrent-per-host 2
uv run --locked job-finder scan --resume     # continue a run that halted on budget
uv run --locked job-finder scan --plain      # no progress bar or colour, plain log lines
```

A live progress bar shows the phase, percentage, elapsed time and a median-based ETA, above a
scrolling per-company log. Some companies genuinely take minutes — Adobe's Workday board needs about
190 individual detail fetches because its listings report "N Locations" instead of naming a city.

Default local outputs:

- `reports/latest_scan.md` — concise report for a person.
- `reports/latest_scan.json` — complete machine-readable accounting, covering all 330 seed companies.
- `state/jobs.sqlite3` — durable identity, evaluation, and aggregate run state.
- `state/llm_costs.jsonl` — append-only record of what each run cost. View with `job-finder costs`.
- `state/resume_checkpoint.json` — written only when a run halts on budget. Valid 24h.
- `state/scan.lock` — overlap protection held only while a scan is running.

The terminal prints registry/profile/prompt and report/state schema versions, then bounded progress
for source collection, deterministic filtering, and candidate evaluation. The final summary shows
source coverage, listing counts, new and duplicate identity counts, result-section counts, and both
report paths. It does not print the gateway key, descriptions, prompts, headers, or model responses.

## Interpret the result

The first bold line in `reports/latest_scan.md` states one of three outcomes:

- `complete` — every enabled source succeeded or returned a verified empty board. Zero matching
  jobs is a valid successful result.
- `partial` — at least one enabled source failed, but healthy-source results remain available.
- `failed` — no enabled source completed successfully.

The report then shows:

1. New strict-ten-day matching jobs.
2. Matching jobs with uncertain publication dates, kept separate under the approved H5 policy.
3. Location, description, relevance, seniority, or provider outcomes requiring review.
4. Complete coverage metrics and source failures.
5. Unsupported and blocked first-release sources with their recorded reasons.

Exit status is `0` for complete coverage, `2` for partial coverage, and `3` for a failed command or
a run where no enabled source completed.

## If the run halts on budget

A scan that exhausts its LLM budget **still writes both reports and exits 0**. Without reading the
last lines you would take it for a completed run that simply found fewer jobs. That is exactly how a
halt went unnoticed on 2026-09-30, stranding 3,026 jobs.

The run ends with:

```
INCOMPLETE: the run budget ran out with 3026 job(s) still unevaluated. They are saved, not lost.
  Resume with:  python -m job_finder scan --resume
  Checkpoint:   state/resume_checkpoint.json (valid for 24h)
```

Nothing is lost. Those rows stay `pending`, and the checkpoint holds them so the resumed run skips
collection and filtering entirely — saving the ~3.5h scrape.

```powershell
uv run --locked job-finder scan --resume
```

Resume is refused, with exit code 5 and an explanation, when the checkpoint is:

- **older than 24h** — postings close, and resuming onto stale data spends budget on rows the next
  scan would retire anyway;
- **built under different rules** — if `profile_version`, `prompt_version` or `model_policy` changed,
  the cached verdicts it would join are themselves invalid;
- **absent or corrupt**.

In every one of those cases the remedy is the same: run a full scan.

Note that lifecycle absence detection is deliberately **skipped** on resume, because a checkpoint
holds only a slice of the listing set and running it would mark live jobs as missing.

If halts are routine rather than exceptional, raise the caps in `.env` — see
`docs/06_llm_provider_configuration.md` and `docs/decisions.md` D4.

## Track what runs cost

```powershell
uv run --locked job-finder costs
```

```
day           runs  evaluated    cost (USD)
2026-09-30       1        140          0.25
2026-10-01       1       3418          6.11
2026-10-02       1         96          0.17

total=USD 6.53 over 3 day(s), 3 run(s), 3654 job(s) evaluated
per_evaluated_job=USD 0.0018
```

The shape to expect is one expensive catch-up day, then cents: the evaluation cache means only
genuinely new postings cost anything. Watch `per_evaluated_job` rather than the total — it moves
only when the prompt, model, or description length changes.

Cost is reported as `unavailable` when no rates are configured, never as zero. The 30-day projection
is labelled as an extrapolation because early backlog runs inflate it.

## Where to find each answer in the report

| Question | Where to look | Notes |
|---|---|---|
| Was coverage complete, partial, or failed? | The first bold sentence and **Coverage and run summary** | `Complete` with zero matches is still a successful run. |
| Which jobs are new strict matches? | **New matching jobs** | |
| Which matches have uncertain publication dates? | **Date-uncertain matching candidates** | Listed separately; these are not strict ten-day matches. |
| Why was each job included or sent to review? | For matches, **Seniority evidence** and **Why it matched**. For reviews, **Review category** and **Reason / evidence**. | Read those cells; do not infer from the title alone. |
| Why was a job rejected? | Not recorded. | Only the three-way verdict is persisted — the model's relevance quote and reasoning are discarded (`docs/decisions.md`, open questions). |
| Which companies had source problems? | **Source failures** | The separate **Unsupported and blocked sources** table records known limitations rather than failures in this run. |
| Where are the full JSON results? | The terminal line beginning `Wrote machine-readable report to` | Defaults to `reports/latest_scan.json`. |
| What did this run cost? | The `llm_cost=` line, or `job-finder costs` | |

## Repeat-run behavior

Do not delete or reset `state/jobs.sqlite3` between normal scans. An immediate unchanged rerun
should show zero repeated jobs and make no repeated LLM request for completed or terminal outcomes.
Uncertain source dates use their persisted first-seen time only for forward aging; first-seen is
never presented as a publication date.

## State safety

Inspect state without showing job descriptions:

```powershell
uv run --locked job-finder state inspect --database state/jobs.sqlite3
```

Back up state to a new file:

```powershell
uv run --locked job-finder state backup --database state/jobs.sqlite3 --output state/backups/jobs-YYYYMMDD.sqlite3
```

Restore a verified backup to a new path without overwriting existing state:

```powershell
uv run --locked job-finder state restore --backup state/backups/jobs-YYYYMMDD.sqlite3 --output state/restored-jobs.sqlite3
```

Reset is not a normal troubleshooting step. It requires an exact resolved-path confirmation and,
for real history, the H7 human-checkpoint protocol in the execution plan.

## Troubleshooting

- `missing required environment variables`: configure the named variables in local `.env`; do not
  paste values into chat.
- `another job-finder scan is already running`: wait for that scan to finish. If no process is
  running, inspect the error and lock path before changing anything.
- `partial`: open the Source failures table. Healthy results are still valid; failed companies are
  not represented as empty boards.
- `failed`: confirm provider configuration, network access, and source diagnostics. The command
  preserves the failed run record and does not claim complete coverage.
- A candidate appears under review: use its direct job link and the recorded reason/evidence. An
  uncertain or invalid seniority result is never promoted to a match.
- `llm_provider_failure` or a transient description-fetch failure: the affected candidate stays
  pending and is retried by the next scan; completed decisions and terminal policy outcomes are
  still reused without another LLM request.

Generated reports and state are ignored by Git. Do not stage them, cached responses, diagnostics,
or `.env`.

## Related documents

- `CLAUDE.md` — architecture and measured numbers.
- `docs/decisions.md` — what was decided and why; read before proposing changes.
- `docs/06_llm_provider_configuration.md` — gateway, budget caps, cost rates.
- `docs/08_source_resilience_and_repair.md` — when a source breaks.
