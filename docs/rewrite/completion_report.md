# to_change.md rewrite — completion report

Built 2026-09-30. Phases 0 through 4 of `to_change.md` are implemented, tested and
committed. The 180-company backlog was descoped by the user partway through and is **not**
included.

## Acceptance

| | baseline | final |
|---|---|---|
| tests passing | 613 | **960** |
| tests failing | 4 | **4** (identical) |
| mypy errors | 4 | **4** (identical) |
| source files type-checked | 119 | 130 |

The 4 test failures are Windows path assertions in `tests/test_smoke.py`
(`config\search_profile.toml`) that cannot pass on Linux. The 4 mypy errors are
Windows-only `msvcrt` calls in `persistence/locking.py`. Both sets are pre-existing and
environmental — they pass on the developer's Windows machine. Details in `baseline.md`.

**No new failure was introduced at any point.** Every phase was verified against the
baseline before committing.

## What landed

**Phase 0 — make failure visible.** The 2026-09-29 run reported `outcome: complete` while
92% of description fetches failed; that is no longer possible. stdlib logging with a
rotating file sink (10MB × 5), a `DetailUnavailable` / `DetailIdentityMismatch` /
`DetailContentMissing` taxonomy applied to 74 raises across ten adapters, the worst
error-swallowing handler fixed, and `ScanAlreadyRunningError` given its own exit code so
an overlapping cron run stops looking like a bad config.

**Phase 1 — root cause.** All 65 local normalization copies deleted, every adapter now
imports the shared module, `filter_verification.py` → `collection.py`, 80 duplicate helper
definitions extracted. A lint guard prevents the copies growing back.

**Phase 2 — scale and integrity.** `CompletionReason` distinguishes an exhausted board
from a page cap, which is what stops silent truncation closing live jobs. Per-host rate
limiting keyed by host (39 Greenhouse companies share one). Bounded thread pool with output
proven byte-identical to sequential.

**Phase 3 — pipeline behaviour.** Location before title; merged relevance + seniority +
location prompt with separate evidence per judgment; the validated title filter integrated
and the regex relevance gate removed; model kept config-driven with mismatch logging.

**Phase 4 — lifecycle.** Per-job probe built on the hardened `source_probe`; absence state
machine with all three guards; schema migration 4 verified non-destructive on a populated
database; expiry dry-run with a four-item checklist; reappearance monitoring by rate.

## Seven places the document was wrong

Each was verified against the repo or the real scan data before acting.

1. **§6.2 "85 handlers, mechanical, no judgment required".** AST classification: 10 are
   `except BaseException: rollback(); raise` (re-raises, nothing lost), 72 are narrow parse
   guards mostly already recording structured diagnostics. Exactly **one** matched the
   description. Blanket-binding all 85 would have been churn.
2. **§6.7's relocation scope.** None of the nine `core/` modules it listed reference
   `filter_verification`; only the 3 relocated modules did. The `core/` ones are imported by
   11 `scripts/` files.
3. **§6.4's uniform treatment.** Variant counts decide safety: `_request_outcome` (1
   variant / 30 files) is free, `_required_string` (14 variants / 28 files) is a behaviour
   change, not an extraction. Left for `core/validation.py`.
4. **§9.4 understates the location change but overstates the risk.** Tuples genuinely
   change shape. Decisions do not: **0/16** filter-decision changes, measured and committed
   as a reproducible script.
5. **§2.1's justification is wrong.** It claims the reorder keeps "~19 Bank of America
   US/10+yr rows out of the review queue (~25% of 128)". All 19 are
   `detail_location_unavailable` — Workday "2 Locations" rows whose detail fetch failed.
   Reordering does not remove them. And 19/128 is 15%, not 25%. The real argument for §2.1
   is that it must precede §2.2a, which is unaffected.
6. **§2.2a and §2.3 must land together.** Integrating the wide title filter while the regex
   relevance gate still existed silently broke everything — that gate fired 10× per scan and
   becomes the universal filter once every title reaches it.
7. **A real bug in `_retry_delay`.** It clamped a server's `Retry-After: 30` to the 4s
   backoff bound, returning 26 seconds early — how a 429 becomes a block. A test had pinned
   the buggy behaviour.

## What needs a real run

Everything was built and verified offline against stub adapters and a stub LLM client, per
the agreed scope. Three things can only be established by running it:

- **Description volume and LLM cost.** The title filter passes 72%/62% versus 11% before —
  roughly 6×, applied to a smaller base now that location runs first. §2.2's estimate of
  1,500–2,500 descriptions per scan remains unverified; the corpora are pre-location samples.
- **The 97 `description_unavailable` rows.** Phase 0 should resolve them into named causes
  and Phase 1 should fix the 78 Google ones outright. Worth checking the first clean run.
- **The §5.1 dry-run week.** The harness enforces its own checklist, and
  `probe_fires_on_first_absence` is the gate on decision F: if the probe does not
  demonstrably fire on first absence, revert the threshold from 3 to 5 until it does.

## Before the first real scan

1. Run the suite on Windows — the 4 environmental failures should disappear.
2. Confirm `JOB_FINDER_LLM_MODEL` is set to what you intend; the startup log now reports
   what the gateway actually returned.
3. Run the scan **without** enabling expiry. The dry-run needs about a week of observations.
4. The §4.3 wipe is a separate explicit step (`job-finder state reset`, which backs up
   first). Per §9.10 it comes after the schema columns — which have now landed — and
   immediately before the dry-run window opens.
