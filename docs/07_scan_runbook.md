# Manual scan runbook

## Purpose

`job-finder scan` collects public listings, applies the rolling-ten-day policy and deterministic
location-before-title filters, retrieves full retained descriptions, then publishes a frozen batch
in SQLite. It evaluates that batch with one merged LLM call per job, reusing an exact cached
judgment where available. The call judges AI/ML relevance, seniority and, only when unresolved,
India eligibility. There is one validation retry. The tool writes local reports and has no
scheduler or notifications.

`evaluate` continues the saved evaluation attempt. `force_reevaluate` starts a new attempt over
the entire saved batch, including previously completed jobs, bypassing the judgment cache.
Neither command revisits company sites or retrieves descriptions. All three use the same OS lock.

## Before the first run

1. Set up Python and dependencies as described in `docs/development.md`.
2. Configure local `.env` variables listed in `docs/06_llm_provider_configuration.md`. Never paste
   keys into chat or commit `.env`.
3. Verify the redacted provider connection:

   ```powershell
   uv run --locked job-finder check-llm
   ```

On upgrade, start with a fresh scan. Old `state/resume_checkpoint.json` files are no longer read;
an explicit `--checkpoint` argument is rejected. The upgrade does not delete existing legacy
files. Existing job identities/first-seen dates survive the schema migration. Legacy judgments
without an exact full-request fingerprint cause a one-time cache miss and may incur new LLM cost.

## Commands and the daily boundary

```powershell
uv run --locked job-finder scan
uv run --locked job-finder scan --discovery-only  # save descriptions, evaluate later
uv run --locked job-finder evaluate
uv run --locked job-finder force_reevaluate
uv run --locked job-finder scan --resume     # alias for evaluate
uv run --locked job-finder scan --plain      # plain progress output
```

**Expect hours for fresh discovery.** The historical 2026-09-30 run collected ~150 sources in
roughly 3.5h and retained 3,677 candidates. Discovery now retrieves all retained descriptions
before the first LLM call. Everything remains sequential. The old ~$7 full-scan estimate used
the configured rates of that run; it is not a current price guarantee.

A batch belongs to the command's admission date in **IST (UTC+05:30)**. New `evaluate` and
`force_reevaluate` invocations are allowed only on that date. A scan admitted at 21:00 leaves
three hours before the midnight boundary. An invocation admitted before midnight may finish
after midnight, including a long discovery stage; if it then stops with pending jobs, another
evaluation invocation is refused and a fresh scan is required. Expiry blocks reuse but does not
automatically delete the stored batch.

| Command | Saved data | Daily log and reports |
|---|---|---|
| `scan` | Immediately discards the previous batch; collects and freezes a new one; evaluates it. | Replaces that date's log/reports and latest copies. |
| `scan --discovery-only` | Collects and filters listings, retrieves full retained descriptions and publishes the batch; leaves every candidate pending without LLM calls or cache reuse. | Replaces the daily log/reports; reports explicitly show deferred evaluation. |
| `evaluate` | Continues pending jobs; completed jobs are retained. A completed attempt regenerates reports without new LLM calls. | Appends to the same dated log; replaces cumulative reports. |
| `force_reevaluate` | Discards the current attempt's progress and starts the whole frozen batch again. Does not re-scrape. | Resets the dated log and replaces the reports. |

If forced evaluation stops, use **`evaluate`** to continue it. Calling `force_reevaluate` again
restarts all jobs again and can spend again. Preserve custom registry/profile/prompt/database,
lock and output flags; the terminal prints a compatible resume command when the batch is fresh.
`--seniority-only` remains a debugging option and bypasses the relevance gate.

To collect now and evaluate later, run `scan --discovery-only`, then `evaluate` before midnight
IST ending the scan's admission date. Descriptions are saved in the current SQLite batch.
Do not run another fresh scan between these commands: it would replace that batch.
No token-budget workaround is needed. If you previously set the temporary PowerShell variable
`JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS=1`, remove that override before evaluation.
The normal model/prompt/provider settings are still loaded to freeze the evaluation configuration;
discovery-only makes no LLM calls. The flag is rejected with `evaluate`, `force_reevaluate` and
`scan --resume`. If discovery itself crosses midnight, the stored batch is already expired for
another evaluation invocation and requires a fresh scan.

`evaluate` rejects changed prompt contents, seniority settings or model/output policy. Use
`force_reevaluate` to apply new evaluation rules to the frozen batch. A changed source registry
or discovery filter requires **a fresh scan**, even for forced evaluation: those changes affect
which jobs the batch should contain.

## What is stored, and for how long

Default locations:

| Data | Location | Retention |
|---|---|---|
| Current full retained batch, descriptions, coverage, evaluation attempt and progress | `state/jobs.sqlite3`: `daily_batch`, `batch_candidates` | One current batch. Removed by a fresh scan, expired-batch prune or reset. Remains physically stored after midnight until one of those actions. |
| Job identity, first-seen, last-seen, lifecycle and latest completed judgment/evidence | Same SQLite database: `jobs` | Persists across scans. Prune clears old descriptions while preserving rows; reset removes job history. |
| Complete reusable judgments keyed by exact request/model policy | Same SQLite database: `evaluation_cache` | Persists across scans; reset clears it. No automatic age limit. |
| Returned replies awaiting validation/commit | Same SQLite database: `llm_requests.response_json` | Cleared when the candidate completes or the attempt is discarded. Available for crash replay until then. |
| Request ID, date, usage, configured rates and discard reason | Same SQLite database: `llm_requests`; export to `state/llm_costs.jsonl` | Permanent accounting, including discarded attempts. Reset/prune preserve it. |
| Daily search log | `state/logs/scan-YYYY-MM-DD.log` | One file per admission date; fresh scan/force resets it, evaluate appends. Older dates have no automatic deletion. |
| Daily report pair and latest copies | `reports/scan-YYYY-MM-DD.json`, `reports/scan-YYYY-MM-DD.md`; `reports/latest_scan.json`, `reports/latest_scan.md` | Replaced for that date; older dates have no automatic deletion. |
| Daily lifecycle baselines and source counts | SQLite: `daily_observations`, `daily_company_counts` | Publication retains the latest observation day's baselines and current/most recent earlier trustworthy source counts. |
| Overlap protection | `state/scan.lock` | OS lock held throughout the command. File presence alone does not mean a command is live. |

Other commands log to `state/logs/commands.log` without altering the search log. Custom output
directories receive the same dated filenames alongside the requested latest output paths.

The historical description average was ~23kB. For 3,677 jobs, full description text is about
85MB per copy. The frozen batch and completed job rows can retain two copies (~170MB), plus
SQLite/metadata overhead. These are estimates; actual size depends on the source descriptions.
All listing-time descriptions may also remain in memory during collection/filtering. Rejected
listing descriptions are not persisted in the frozen batch.

## Failure and recovery

| Event | Result | Next step |
|---|---|---|
| Fatal failure/interruption before the discovery transaction publishes | No new batch or partial job/lifecycle writes. Previous batch stays discarded. Partial daily artifacts are removed; a small failure diagnostic remains. Durable history and spending survive. | Fresh `scan`. |
| Some individual sources fail but at least one succeeds or is valid-empty | Healthy-source batch remains, marked partial coverage. Failed sources are not treated as empty boards. | Evaluate it normally; inspect source failures. |
| No enabled source succeeds or returns valid-empty | Fatal discovery failure; no batch. | Fix the source/configuration problem and run a fresh `scan`. |
| One description cannot be retrieved | That candidate's frozen batch record becomes description review; other candidates proceed. Evaluation does not retry website retrieval. | A fresh `scan` is needed to fetch it again. |
| LLM budget exhausted or provider unavailable | Stop the invocation; completed judgments and all pending candidates stay saved. Partial cumulative reports are written. | `evaluate` before midnight IST. |
| Crash/interruption after batch publication, including a report write failure | Batch/progress and request journal survive. Report files can temporarily be absent or from different write steps; each file replacement is atomic, the pair is not a filesystem transaction. | `evaluate` regenerates cumulative reports before midnight IST. |
| Invalid model output after the bounded validation retry | A terminal review outcome is saved, with usage preserved. It is not a pending provider outage. | `force_reevaluate` if another complete evaluation is desired. |

Returned replies saved before a crash are replayed locally without another paid call or consuming
the next invocation's request budget. A crash while the provider call is in flight can leave no
saved reply. Its usage is marked **unknown**, and a replacement request may incur another charge.
There is no exactly-once billing guarantee. A valid reply without provider usage can complete a
judgment, while its spending remains unknown.

Exit statuses:

| Code | Meaning |
|---|---|
| `0` | Evaluation complete; complete enabled-source coverage, including valid zero matches. With `--discovery-only`, successful complete discovery with evaluation deferred. |
| `2` | Evaluation complete; partial source coverage. With `--discovery-only`, successful partial discovery with evaluation deferred. |
| `3` | Fatal command/discovery failure. |
| `4` | Another command holds the scan lock; admission/output replacement did not proceed. |
| `5` | Saved batch unavailable, expired, corrupt or incompatible; also retired `--checkpoint` use. |
| `6` | Evaluation incomplete with pending candidates, usually budget/provider halt. |
| `130` | Interrupted. Recovery depends on whether discovery was published. |

## Reading reports

Coverage and evaluation completion are separate. Complete source coverage does **not** mean all
jobs were judged. The bold outcome and pending count identify this explicitly. After resume, the
report contains the whole current attempt, not only the jobs evaluated in the latest invocation.
Forced evaluation's report contains only its new attempt's completed decisions, never results
left over from the discarded attempt.

| Question | Where to look |
|---|---|
| Which strict matches are new? | **Matching jobs (new and known)**: use the identity column. Known/cached matches remain visible. |
| Which matches lack verified publication dates? | **Date-uncertain matching candidates**; these are separate from strict ten-day matches. |
| Why is a job included or under review? | Relevance/evidence/reason cells and **Candidates requiring review**. |
| Which companies failed? | **Source failures**; unsupported/blocked sources are separately accounted for. |
| Did all jobs finish? | Evaluation completion and pending count; **LLM usage** lists requests with unknown usage. |
| Where is complete company accounting? | JSON report covers all 330 canonical companies, including disabled/unsupported reasons. |

Relevance rejects unrelated jobs, so fewer matches than evaluated candidates is expected. Complete
merged judgments, including rejection evidence, are stored in the cache/database; rejected jobs
are not expanded into match tables. The historical 2026-09-30 sample rejected 153 of 259 evaluated
jobs (59%); that is an observation about that sample, not a promised future rate.

## Spending and repeat runs

```powershell
uv run --locked job-finder costs
```

Costs reads SQLite request accounting and the exported ledger, deduplicating request IDs and
keeping legacy run-level entries readable. Spending is assigned to the actual request date in
IST, which can differ from the batch date if a command crosses midnight. Rates are captured
from the local configuration at request time; reported money is an estimate using those rates.

Discarded requests remain in the total, with discarded amounts/counts shown alongside it. A
force or replacement does not refund prior calls. Currencies are totaled separately. Missing
usage/rates are reported as unknown/unavailable, not free. If export fails, request accounting
remains in SQLite and `costs` can read it there. Restoring an older database does not undo
spending/discard events already exported to the permanent ledger.

Do not reset the database between normal scans. An unchanged full request reuses the complete
judgment without a new LLM call, but a fresh scan still retrieves source listings/descriptions
to detect changes. Same-day replacements recompute lifecycle from that day's baseline, so they
cannot repeatedly increment sightings or absences. Evaluate/force never run lifecycle absence
detection. Expiry remains observational by default; existing opt-in expiry safety still applies.

## State safety

```powershell
uv run --locked job-finder state inspect --database state/jobs.sqlite3
uv run --locked job-finder state backup --database state/jobs.sqlite3 --output state/backups/jobs-YYYYMMDD.sqlite3
uv run --locked job-finder state restore --backup state/backups/jobs-YYYYMMDD.sqlite3 --output state/restored-jobs.sqlite3
```

Inspect separates durable job-history counts from the current batch's candidate/pending/freshness
counts. This matters during forced evaluation: an old completed job judgment is not completion
of the new attempt. Backups include frozen batch, progress and request journal. Backup/restore
accept older supported schemas (1–6); writing commands migrate them. Restore creates a new file
and refuses to overwrite existing state. Restoring does not extend a batch's admission date.

Prune clears descriptions not seen in 90 days, protects fresh batch candidates, and removes an
expired batch. It preserves identity/first-seen rows and spending. Reset clears jobs, cache,
batch and lifecycle data but preserves spending. Both acquire the scan lock and require a verified
backup and exact resolved database-path confirmation. Reset is not a normal troubleshooting step;
the existing H7 human approval rule applies before resetting real history. Erasing identities
would make still-live undated jobs look newly seen.

**Never run the test suite while a scan is live.** Tests use disposable state but also contend
for the default scan lock. Generated state/reports, replies, diagnostics and `.env` stay out of Git.

## Related documents

- `CLAUDE.md` — architecture, historical measurements and known traps.
- `docs/decisions.md` — D12 records the daily recovery/accounting design and reasons.
- `docs/06_llm_provider_configuration.md` — provider, budget caps and cost rates.
- `docs/08_source_resilience_and_repair.md` — source failures and repair.
