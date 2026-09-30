# to_change.md rewrite — completion report

Built 2026-09-30. Phases 0 through 4 of `to_change.md` are implemented, tested and
committed. The 180-company backlog was descoped by the user partway through and is **not**
included.

## Acceptance

| | baseline | final |
|---|---|---|
| tests passing | 613 | **975** |
| tests failing | 4 | **0** |
| mypy errors | 4 | **4** (identical) |
| source files type-checked | 119 | 132 |

The 4 remaining mypy errors are Windows-only `msvcrt` calls in `persistence/locking.py`,
pre-existing and environmental. The 4 test failures that persisted through the whole build
were Windows path assertions; they were fixed last, deliberately, because they were the
recorded baseline every phase was measured against.

**No new failure was introduced at any point.** Every phase was verified against the
baseline before committing.

## Wiring (the gap that mattered)

Phases 3 and 4 were built, tested and verified as components, but `scan.py` did not call
them. The pipeline had the widened title filter with **no relevance gate behind it**, no
lifecycle tracking, and v4 columns that nothing wrote. That is now closed:

- **Merged LLM call wired.** `MergedEvaluator` mirrors `SeniorityEvaluator`'s surface, so
  the cache service and scan consume either. `scan.py` enforces the relevance verdict --
  only a confident `unrelated` drops a row; `peripheral` displays tiered lower (2.6).
  Location is asked only when the deterministic filter returned REVIEW, enforced in the
  response *schema* so the model cannot contradict a settled decision.
- **Lifecycle wired.** Sightings and absences recorded per job, company trustworthiness
  built from the real `CompletionReason`, probe firing on first absence, verdict_at set
  once via COALESCE. Expiry defaults to dry run.
- **Dry-run and reappearance surfaced** on the CLI. `--enable-expiry` is opt-in and is
  *refused* alongside `--no-probe`, since at 3 absences the probe is the whole safety
  margin (10.F).

Verified against the live gateway on the case that motivated it: `Lead Salesforce
Developer, GTM Systems` is dropped as `unrelated` with cited evidence, while
`Machine Learning Engineer, Search Quality` is kept. Both pass seniority, so only the
relevance gate separates them.

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

## Live verification (2026-09-30)

The build was done offline, then verified against the real gateway and real company
boards. Four things were confirmed and two problems were found.

**Confirmed.**

- `JOB_FINDER_LLM_MODEL` is `gpt-5.6-luna`, matching decision D. This closes the fourth
  readiness gap -- the name could not be verified from the repo alone at the start.
- A live collection run over three Greenhouse companies (glean, moloco, rubrik) fetched
  300 listings successfully, with rate limiting applied and `healthy: True`.
- The Phase 1 normalization fix works on live titles: commas, hyphens and parentheses are
  stripped as intended.
- The merged prompt scores **19/20** against the relevance eval set on the real model --
  9/9 substantive, 4/4 peripheral, 6/7 unrelated, including all four documented failure
  modes. The single disagreement is `Technical Program Manager, ML Platform`, where the
  model said `peripheral` and the eval set says `unrelated`. The model's call is arguably
  better, and under 2.6 `peripheral` displays anyway. Deliberately not relabelled: an eval
  set that agrees with the model by construction measures nothing.

**Found and fixed: evidence quoted from the title was rejected.** When a description
states no experience requirement, the model correctly answers `uncertain` and quotes the
job title as evidence. `parse_merged_response` validated against the description alone and
discarded the *entire* response -- including two correct judgments. One unquotable
sub-judgment destroying two sound ones is exactly the collapse 2.5 exists to prevent.
Evidence is now checked against every text the model was shown; a quote from neither is
still rejected.

**Found and fixed: the gateway serves a dated pin.** `gpt-5.6-luna` resolves to
`gpt-5.6-luna-2026-07-09`. The new logging caught this immediately, which is the point --
without it there would be no record of which model produced a given scan's verdicts. It
initially logged at WARNING on every run; since a dated pin is a *more specific* answer to
the same request rather than a substitution, it is now INFO (`llm_model_pinned`). A
genuinely different model still warns. Warning on every run trains the reader to ignore
the warning that matters.

## What still needs a full run

Three things remain unestablished, all requiring a complete scan rather than a sample:

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
