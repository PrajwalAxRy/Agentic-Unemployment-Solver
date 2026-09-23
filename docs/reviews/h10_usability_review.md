# H10 manual-scan usability review

## Checkpoint status

**APPROVED — Human checkpoint H10 completed on 2026-09-23.**

The user followed the usability instructions and replied `usable`. Phase 9 implementation,
technical validation, and the required human review are complete. This approval confirms that a
person who did not implement the command can follow the runbook and interpret the result; it does
not change the approved search, date, or seniority policies.

## Known-good technical evidence

The deliberate fresh-state run used the ignored disposable database
`state/phase9_validation.sqlite3` and accounted for all 330 canonical companies. It attempted all
86 enabled sources, observed 25,687 listings, retained 332 candidates, and created 332 identities.
It finished `partial` because Workday exhausted a transient malformed-page retry; all 83 other
nonempty sources succeeded and two sources were verified empty. The partial report kept healthy
results and identified Workday separately rather than treating it as empty.

A targeted Workday verification immediately passed with 366 listings across 19 pages. The
same-state recovery run then completed all 86 enabled sources with 84 successful and two verified
empty outcomes, 26,062 listings, 335 retained candidates, three genuine new Workday identities,
and 332 suppressed duplicates. Only those three new identities reached the LLM; two became new
date-uncertain matches and one was rejected. The representative human-readable result is
`reports/phase9_scan_recovery.md` and its complete machine-readable companion is
`reports/phase9_scan_recovery.json`.

The first unchanged retry-validation pass then completed with zero new identities and zero
reported matches. It retried 16 technical outcomes found by the fresh run, recovered seven as
valid seniority decisions, and did not repeat any earlier match. This live evidence exposed and
fixed the distinction between terminal H9 decisions and retryable provider or description-fetch
failures.

The definitive post-fix pass completed at `2026-09-23T10:31:53+05:30` with:

- 330 canonical companies and all 244 disabled companies carrying a nonempty reason.
- 86 enabled and attempted companies; 84 successful, two verified empty, and zero failed sources.
- 26,020 listings; 12,889 recency candidates; 1,301 role candidates; 321 retained candidates; and
  22 location-review candidates.
- Zero new identities, 311 suppressed duplicates, zero new strict or date-uncertain matches, and
  zero successful LLM re-evaluations of completed decisions.
- 166 completed-decision cache hits. Three provider-empty responses and six unavailable
  descriptions remain explicit review rows and eligible for a later retry; they are not promoted
  to matches.
- 330 machine-accounting rows and zero disabled rows without an explanation.
- Durable state with 335 identities: 171 completed, 161 deterministic/terminal failures, and
  three pending provider retries. All four Phase 9 run rows finished durably.

The definitive outputs are `reports/phase9_scan_postfix.md` and
`reports/phase9_scan_postfix.json`. Generated reports and state are ignored by Git.

## Exact usability review

1. Open `docs/07_scan_runbook.md` and follow it from the repository root.
2. Run:

   ```powershell
   uv run --locked job-finder scan
   ```

3. Open `reports/latest_scan.md`. Use `reports/latest_scan.json` only when complete 330-company
   accounting is needed.
4. Answer these questions without reading source code:
   1. Was enabled-source coverage complete, partial, or failed?
   2. Which jobs are new strict matches?
   3. Which otherwise matching jobs have uncertain dates?
   4. Why was each displayed job included or sent to review?
   5. Which companies need source attention?
   6. Where are the complete machine-readable results?
   7. Where are state inspection, backup, restore, and reset instructions?
5. Reply `usable` if the command, report, and runbook made all seven answers clear. Otherwise list
   the question or step where the interface became confusing.

The current 86-source run takes tens of minutes; the measured Phase 9 runs ranged from about 24 to
42 minutes. Terminal progress should continue throughout source collection, deterministic
filtering, and candidate evaluation.
