# Manual scan runbook

## Purpose

`job-finder scan` runs the complete first-release discovery pipeline once. It reads public sources,
applies the approved rolling-ten-day, role, and India-location policies, suppresses previously
processed jobs, evaluates seniority, and writes local reports. It does not schedule another run or
send a notification.

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

The current 86-source validation takes tens of minutes (about 42 minutes in the Phase 9 baseline),
depending on public-source and LLM response times. Keep the terminal open while progress advances.

Default local outputs:

- `reports/latest_scan.md` — concise report for a person.
- `reports/latest_scan.json` — complete machine-readable accounting, including all 330 companies.
- `state/jobs.sqlite3` — durable identity, evaluation, and aggregate run state.
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
3. Location, description, seniority, or provider outcomes requiring review.
4. Complete coverage metrics and source failures.
5. Unsupported and blocked first-release sources with their recorded reasons.

Exit status is `0` for complete coverage, `2` for partial coverage, and `3` for a failed command or
a run where no enabled source completed.

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

## H10 usability checklist

After following this runbook, a reviewer should be able to answer:

1. Was enabled-source coverage complete, partial, or failed?
2. Which jobs are new strict matches?
3. Which otherwise matching jobs have uncertain dates?
4. Why was each displayed job included or sent to review?
5. Which companies need source attention?
6. Where are the complete machine-readable results?
7. Where are state inspection, backup, restore, and reset instructions?
