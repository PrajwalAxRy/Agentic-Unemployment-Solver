# Phase 11 full-registry pilot log

Status: **third-day attempt partial on 2026-09-27; STOP at Human checkpoint H4 for Atomicwork.**

The pilot has covered 2026-09-25 and 2026-09-26. Same-day reruns prove duplicate behavior but do
not count as another pilot day. The 2026-09-27 attempt does not count as the third clean day because
Atomicwork's former Greenhouse source moved. The normal job-history database was preserved. Resolve
the coverage exception in `phase11_atomicwork_coverage_review.md` before resuming H12.

## Release-candidate configuration snapshot

The final configuration used for the clean run and immediate duplicate check is:

| Item | Value |
|---|---|
| Git commit | `2161d0e0bfd5410848493d02bec6fca63e601988` |
| Package / adapter implementation | `job-finder 0.1.0` |
| Registry | `0.2.0-phase4` |
| Search profile | `india-ai-ml-under-five-years` version `1.1.2` |
| Canonical report profile hash | `45f8deb028a4fc900da37aeb52c519cc78747bbc7b5d2b45f069df7bd4a36e60` |
| Seniority prompt | `1.0.1` |
| Model policy | `amd-llm-gateway:gpt-5.6-luna:v1` |
| Report schema | `1` |
| State schema | `3` |
| Python | CPython `3.12` |

Tracked configuration SHA-256 values:

- `config/company_sources.json`:
  `DA5F812385568EBC41091003A46CF0C0A166EBCA66F99F06A0E5645048D3A249`
- `config/search_profile.toml`:
  `84C9C8C091A15F9CEEF6F13EB058A41BFC205F13F2507F194DF39C87C142A604`
- `config/seniority_prompt.toml`:
  `1DBD10716EADD2A3B2173556AA90A950A6C9CFE524034ED045EEECCB35FCCEB6`

The 86 enabled sources use the reviewed implementations for Ashby (25), Darwinbox (4),
Eightfold (1), Greenhouse (25), Jobvite (1), Lever (11), Oracle Cloud (2), SmartRecruiters (3),
SuccessFactors (1), and Workday (13). The registry also accounts for all 244 disabled, deferred,
blocked, or unsupported companies.

## State baseline and safety

- The pilot deliberately began with the existing `state/jobs.sqlite3`, schema `3`: 326 records,
  18 pending, 156 completed, and 152 failed. It was not reset.
- A pre-pilot verified copy is retained locally at
  `state/backups/phase11_2026-09-25_pre_pilot.sqlite3`.
- A second local copy at `state/backups/phase11_2026-09-25_pre_postfix.sqlite3` captures the
  371-record state after the first run and before post-defect scans.
- After the final immediate rerun, state contains 393 records: 24 pending, 193 completed, and 176
  failed. Pending and failed technical outcomes remain eligible for retry; completed decisions are
  versioned and suppress repeat display.
- Before the 2026-09-26 scan, a verified local backup and restore check preserved all 393 records
  at `state/backups/phase11_2026-09-26_pre_scan.sqlite3` and
  `state/backups/phase11_2026-09-26_pre_scan_restore_check.sqlite3`.
- After the 2026-09-26 scan, state still contains 393 records: 22 pending, 195 completed, and 176
  failed. Two retryable provider outcomes reached terminal uncertain decisions; no new identity was
  added.
- Before the 2026-09-27 attempt, a verified local backup and restore check preserved all 393
  records at `state/backups/phase11_2026-09-27_pre_scan.sqlite3` and
  `state/backups/phase11_2026-09-27_pre_scan_restore_check.sqlite3`.
- The partial attempt added one JPMorganChase identity with a visible terminal technical outcome.
  State now contains 394 records: 22 pending, 195 completed, and 177 failed. Atomicwork has no
  persisted candidate records, so no state migration is currently required by its source change.
- No normal pilot run restored, reset, or replaced the database. Checkpoint H7 was not triggered.

The local databases, reports, and backups remain ignored and must not be committed.

## Run chronology

All times below are Asia/Calcutta on the listed date.

| Run | Date | Profile | Time | Status | Sources success / empty / failed | Listings | New / duplicate-suppressed | Strict / uncertain / review | Duration |
|---|---|---:|---|---|---:|---:|---:|---:|---:|
| `scan-20260925T035057Z-f8166432` | 2026-09-25 | `1.1.0` | 09:20:57–09:48:28 | complete | 84 / 2 / 0 | 26,116 | 45 / 282 | 4 / 4 / 52 | 1,650.665 s |
| `scan-20260925T042319Z-82cd2e17` | 2026-09-25 | `1.1.1` | 09:53:19–17:36:14 | failed | stopped during source collection | — | — | — | 7 h 42 m 55 s |
| `scan-20260925T120833Z-f16f049a` | 2026-09-25 | `1.1.1` | 17:38:33–18:41:08 | complete | 84 / 2 / 0 | 26,142 | 20 / 0 | 0 / 0 / 40 | 3,755.766 s |
| `scan-20260925T131248Z-a0c866e6` | 2026-09-25 | `1.1.1` | 18:42:48–19:16:44 | complete rerun | 84 / 2 / 0 | 26,136 | 1 / 304 | 1 / 0 / 47 | 2,036.683 s |
| `scan-20260925T135115Z-dc5432db` | 2026-09-25 | `1.1.2` | 19:21:15–20:12:49 | complete | 84 / 2 / 0 | 26,120 | 1 / 0 | 1 / 0 / 36 | 3,093.963 s |
| `scan-20260925T144452Z-39d54451` | 2026-09-25 | `1.1.2` | 20:14:52–20:47:03 | complete rerun | 84 / 2 / 0 | 26,114 | 0 / 311 | 0 / 0 / 42 | 1,930.679 s |
| `scan-20260926T000739Z-2cef6bde` | 2026-09-26 | `1.1.2` | 05:37:39–06:01:50 | complete | 84 / 2 / 0 | 26,194 | 0 / 303 | 0 / 0 / 34 | 1,450.330 s |
| `scan-20260927T173616Z-6766cac6` | 2026-09-27 | `1.1.2` | 23:06:16–23:33:03 | partial | 83 / 2 / 1 | 26,125 | 1 / 288 | 0 / 0 / 29 | 1,607.311 s |

The failed `1.1.1` attempt was durably closed as `failed`; it did not mutate job state because it
stopped before filtering and evaluation. It is retained in the chronology rather than being
silently discarded.

Ignored local report artifacts:

- `reports/phase11_pilot_2026-09-25.json`
- `reports/phase11_pilot_2026-09-25_postfix.json`
- `reports/phase11_pilot_2026-09-25_postfix_rerun.json`
- `reports/phase11_pilot_2026-09-25_postfix_v112.json`
- `reports/phase11_pilot_2026-09-25_v112_rerun.json`
- `reports/phase11_pilot_2026-09-26.json`
- `reports/phase11_pilot_2026-09-27.json`
- `reports/phase11_atomicwork_2026-09-27_targeted.json`

Each successful run also has a same-basename Markdown report.

## Detailed pilot metrics

### Initial run (`1.1.0`)

- 330 canonical companies accounted for; 86 attempted; 244 disabled or deferred.
- 13,384 recency candidates, 1,369 role candidates, and 346 retained candidates.
- 22 location reviews; 55 description fetches; 18 description failures.
- 14 conditional-title passes and 14 conditional-title rejections.
- 26 LLM evaluations and 150 cache hits.
- Seniority outcomes: 8 matches, 11 rejections, and 53 review outcomes.
- Usage: 32 requests, 40,131 measured input tokens, and 4,594 measured output tokens.

All eight displayed matches were reviewed. Seven were valid under the approved policy:

- strict: Observe.AI `AI Agent Engineer` and JPMorganChase `Data Scientist Associate` jobs
  `210790242` and `210791112`;
- uncertain-date: Visa `Sr. ML Engineer`, Visa `Sr. Software Engineer (3 - 6 years of experience
  in Oracle EBS, R12 development)`, Visa `Software Engineer (1 - 2 years of experience in Python,
  GenAI, ML, Deep Learning)`, and Palo Alto Networks `AI Engineer, Agentic Systems (Quality
  Engineering)`.

JPMorganChase `Software Engineer III-Tandem Developer` (`210786170`) was a false positive. The
official description concerned Tandem, COBOL, payments, and using coding assistants; a generic
technology taxonomy was the only AI/ML evidence. It is now rejected as `incidental_ai_only`.

The 52 review rows were inspected: 18 `description_unavailable`, 20
`detail_location_unavailable`, six `llm_provider_failure`, two `missing_location`, and six
`seniority_uncertain`. All remained visible and none was promoted without evidence.

Fourteen newly rejected conditional-title candidates were sampled: 13 were `no_ai_topic` and one
was `topic_action_not_connected`. The sample found no false rejection.

### Clean post-network-fix run (`1.1.1`)

- 13,389 recency candidates, 1,350 role candidates, and 332 retained candidates.
- 243 description fetches and eight description failures.
- 62 conditional-title passes and 144 rejections.
- 161 LLM evaluations, zero cache hits after the profile version change.
- Seniority outcomes: 55 matches, 84 rejections, and 71 review outcomes.
- Usage: 180 requests, 227,797 measured input tokens, and 25,377 measured output tokens.
- No new strict or uncertain-date match was displayed. All 40 review rows were inspected.
- Both the Tandem false-positive ID and its title were absent from the JSON and Markdown reports.

The immediate `1.1.1` rerun suppressed 304 completed decisions but discovered a genuinely new live
identity, JPMorganChase `Software Engineer II - Java Full Stack Developer + AWS + AI`
(`210788786`). Its official description showed conventional Java/AWS full-stack work plus use of
Copilot, LLM, Claude Code, and other AI coding assistants. That is outside the approved substantive
AI-work scope and led to profile `1.1.2`.

### Final clean run (`1.1.2`)

- 13,380 recency candidates, 1,352 role candidates, and 332 retained candidates.
- 22 location reviews; 244 description fetches; eight description failures.
- 63 conditional-title passes and 143 conditional-title rejections.
- 169 LLM evaluations and zero cache hits after the profile version change.
- Seniority outcomes: 57 matches, 85 rejections, and 69 review outcomes.
- Usage: 181 requests, 237,849 measured input tokens, and 27,053 measured output tokens.
- Neither `210786170` nor `210788786` appeared in any displayed report section.

The one new strict match was reviewed and accepted:

- JPMorganChase `Data Scientist Associate` (`210794862`), Bengaluru, published 2026-09-25. The
  official description centers on generative-AI use cases, AI-model integration, building and
  testing AI agents, and monitoring model performance. Its required qualification permits four
  years of AI/ML or data-science experience, below the five-year threshold.

There were no new date-uncertain matches. The 36 review rows were inspected: 20
`detail_location_unavailable`, eight `description_unavailable`, four `llm_provider_failure`, two
`missing_location`, and two `seniority_uncertain`. No enabled source failed.

### Final immediate duplicate check (`1.1.2`)

- 13,381 recency candidates, 1,349 role candidates, and 331 retained candidates.
- Zero new identities; 311 completed duplicates suppressed.
- Zero strict matches and zero date-uncertain matches displayed again.
- 169 LLM cache hits and only seven live LLM evaluations for retryable outcomes.
- Usage: 11 requests, 10,527 measured input tokens, and 1,689 measured output tokens.
- The 42 visible review rows were unresolved retry/review outcomes: 20
  `detail_location_unavailable`, nine `description_unavailable`, four `llm_provider_failure`, two
  `missing_location`, and seven `seniority_uncertain`.

Live source inventories changed slightly between same-day runs. The duplicate gate nevertheless
passes because the final-profile rerun found zero new identities and displayed no completed match
again.

### Second clean day (`1.1.2`, 2026-09-26)

- The frozen configuration identifiers and all three tracked configuration hashes matched the
  release-candidate snapshot before the run. Commit `2161d0e` remained an ancestor of `HEAD`; the
  only tracked changes after it were pilot documentation and its artifact-contract test.
- `scan-20260926T000739Z-2cef6bde` accounted for all 330 companies: 84 successful sources,
  Deeptune and Rapido valid-empty, 244 disabled or deferred companies, and zero failed sources.
- The run observed 26,194 listings, 13,383 recency candidates, 1,316 role candidates, and 314
  retained candidates. It found zero new identities, suppressed 303 completed duplicates, and
  displayed no strict or date-uncertain match.
- Candidate evaluation reused 171 cached decisions, made two live evaluations for retryable
  outcomes, and used three gateway requests with 2,918 measured input and 505 measured output
  tokens.
- All 34 review rows were inspected: 21 `detail_location_unavailable`, eight
  `description_unavailable`, two `missing_location`, two `seniority_uncertain`, and one
  `llm_provider_failure`. None was promoted to a match.
- Two Barclays gateway failures from the final 2026-09-25 rerun resolved to explicit
  `seniority_uncertain` decisions. One JPMorganChase no-completion outcome remains retryable. One
  additional Bank of America listing entered the known detail-location review lane, while nine
  former review rows were absent from the current live/recency candidate set.
- Both saved incidental-AI false-positive IDs remained absent from every displayed section. No
  new false positive, false negative, source exception, or systematic filter defect was found.
- State remained at 393 identities and moved from 24 pending / 193 completed / 176 failed to 22
  pending / 195 completed / 176 failed as the two retryable evaluations resolved.

### Third-day partial attempt (`1.1.2`, 2026-09-27)

- Frozen configuration identifiers and hashes matched before the run. State was backed up and
  restore-verified without reset or replacement.
- `scan-20260927T173616Z-6766cac6` accounted for all 330 companies but finished `partial`: 83
  successful sources, Deeptune and Rapido valid-empty, Atomicwork failed, and 244 companies
  remained explicitly disabled or deferred.
- Healthy sources produced 26,125 listings, 12,896 recency candidates, 1,268 role candidates, and
  295 retained candidates. The run found one new identity, suppressed 288 completed duplicates,
  and displayed no strict or uncertain-date match.
- All 29 review rows were inspected: 21 `detail_location_unavailable`, five
  `description_unavailable`, two `missing_location`, and one `llm_provider_failure`. None was
  promoted to a match.
- Atomicwork alone exhausted three source attempts with `http_error`; the targeted verifier then
  reproduced the failure across three more attempts and categorized it as `source_moved`.
- First-party inspection found six current official Webflow job pages and a matching public
  sitemap, while the former Greenhouse API returns 404. This attempt is preserved as valid failure
  visibility evidence but does not count as the third clean pilot day.
- Sanitized request `repair-067463ff973ca40d` and the coverage choices are documented in
  `docs/reviews/phase11_atomicwork_coverage_review.md`. Active configuration is unchanged.

## Defects and regression history

1. `d0ba02e` — added a regression and rejected generic AI technology lists that made Tandem
   payments development appear to be AI work; profile `1.1.1`.
2. `719976e` — added a regression and contained `http.client.RemoteDisconnected` and equivalent
   connection closures as sanitized retryable network errors. The original full scan had aborted
   at Palo Alto Networks; three later full scans collected that source successfully.
3. `2161d0e` — added a high-fidelity regression for conventional full-stack roles centered on AI
   coding assistants and productivity tools; profile `1.1.2`. The exact live job now returns
   `incidental_ai_only`.

Focused tests passed after each fix. The final repository gate passed Ruff formatting, Ruff lint,
strict mypy, and 465 tests.

## Coverage, quality, and limitations

- Registry accounting passes: all 330 canonical companies are successful, valid-empty, disabled,
  unsupported, blocked, or otherwise deferred with an explicit reason.
- Every completed full run had 84 successful sources, Deeptune and Rapido as the two valid-empty
  sources, and zero failed sources.
- Duplicate behavior passes on the unchanged final profile: zero new identities, 311 suppressed
  duplicates on the immediate rerun; the next-day run also found zero new identities, suppressed
  303 completed duplicates, and displayed no repeated match.
- Two clean calendar days, 2026-09-25 and 2026-09-26, now pass complete source coverage and
  duplicate behavior. A third later-day run remains before release review because the execution
  plan requires scans on several different days.
- Reviewed role/location samples have no remaining systematic defect after the two incidental-AI
  regressions. Seniority quality remains governed by the H9-approved threshold.
- Uncertain publication dates, locations, descriptions, provider failures, and seniority outcomes
  remain visible in separate report sections.
- Phase 10 failure drills and the live disconnect regression ensure a known broken source does not
  appear as a healthy empty result.
- The H10-approved operating instructions remain in `docs/07_scan_runbook.md`; source diagnosis
  and repair instructions remain in `docs/08_source_resilience_and_repair.md`.

Known release limitations remain explicit:

- NVIDIA and PayPal are H4-approved unsupported Eightfold sources with manual public-page
  fallbacks; access controls were not bypassed.
- 244 registry rows are disabled, deferred, blocked, or unsupported, including the documented
  custom-adapter backlog and source conflicts.
- Bank of America multi-location detail retrieval produces visible location-review rows.
- Some SAP, SmartRecruiters, and other listings expose no usable full description and remain
  visible for review.
- The AMD gateway intermittently returns no completion text for a small set of jobs; these remain
  retryable `llm_provider_failure` rows.
- Quantbox Research's eight old `first_published` values remain a reviewed
  `stale_publication_dates` anomaly rather than a hidden failure.

## CONDITIONAL STOP — Human checkpoint H4: Atomicwork coverage exception

The first and second clean pilot days, 2026-09-25 and 2026-09-26, still pass. The 2026-09-27
attempt is correctly retained as partial and does not satisfy the final different-day gate.
Atomicwork is a P1 company whose public source changed from Greenhouse to official Webflow pages.
Continuing now requires an explicit coverage disposition.

**STOP — Human checkpoint H4.** Review
`docs/reviews/phase11_atomicwork_coverage_review.md` and reply either
`build Atomicwork custom adapter` (recommended) or
`mark Atomicwork unsupported for first release`. Do not resume H12 or change active source
configuration until this decision is recorded.
