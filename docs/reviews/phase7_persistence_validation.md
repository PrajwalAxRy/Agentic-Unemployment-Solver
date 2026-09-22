# Phase 7 duplicate-persistence validation

## Gate status

**Passed on 2026-09-23.** The final complete-registry continuation pass checked all 86 enabled
sources, observed 26,051 listings, retained 333 candidates, and produced zero new identities
against the disposable 336-record validation history. Source outcomes were 84 successful and two
valid empty, with no failed, partial, blocked, or suspicious sources.

The machine-readable local report is `reports/phase7_persistence_verification_final.json`. Reports
and SQLite state remain ignored and are not committed.

## Identity and idempotency evidence

- Every one of the 336 identities accumulated during the live validation used the preferred
  `company_id + source_type + external_job_id` strategy.
- No URL or fallback-fingerprint identity was needed, so there was no live fallback merge to
  adjudicate. Fixture tests cover tracking-parameter stability, harmless whitespace and location
  ordering, department separation, and distinct external requisition IDs.
- The initial two-pass run observed 332 retained identities, followed by three genuine Workday
  requisitions that appeared during the hour-long live collection. Each had a distinct external ID
  and canonical URL; none represented identity churn.
- A later continuation added one genuine JPMorganChase requisition after the calendar rolled into
  23 September. The immediate pass after that produced zero new identities despite broad transient
  network failures, separating source availability from identity behavior.
- The final healthy pass produced zero new identities. The store remained at 336 historical
  identities while 333 were retained in that current scan, as expected when live inventory changes.

## Source defect found and corrected

Bank of America's active Workday inventory changed totals during pagination and returned an
overlapping requisition plus exact identifier-only placeholder rows. The pre-fix adapter treated
the overlap as suspicious even though stable external IDs made safe de-duplication possible.

A failing regression was added before the shared Workday fix. When the source reports inventory
total drift, the adapter now fetches every requested offset, retains each unique requisition once,
and emits warning diagnostics for drift, duplicates, and placeholders. Duplicate IDs without
reported inventory drift remain suspicious. The final live pass exercised the corrected behavior
without a source-health failure.

## Transaction and cache evidence

- New observations are committed as `pending` before description retrieval or LLM work.
- Pending rows survive process interruption and are returned in deterministic retry order.
- Completed results are reused only when job identity, description hash, profile version, and
  prompt version match.
- Description, profile, or prompt changes retain job identity while invalidating the cached
  evaluation.
- The operating-system scan lock rejects overlapping runs and releases after clean completion or
  exceptions.

## Maintenance drill

The documented commands created a verified backup of the disposable 336-record database and
restored it to a new path. Inspection reported schema version 1 and identical counts for the
source, backup, and restored database. Backup and restore refuse to overwrite existing files.
Reset requires an exact resolved-path confirmation and first creates a verified backup.

No real job-history database existed or was modified, so conditional checkpoint H7 was not
triggered.

## Validation

Repository validation passes with 356 tests, strict mypy, Ruff formatting, and Ruff lint. Phase 7
is complete: unchanged retained candidates produce zero new identities, pending work is durable,
overlapping scans are blocked, and state maintenance is documented and tested.
