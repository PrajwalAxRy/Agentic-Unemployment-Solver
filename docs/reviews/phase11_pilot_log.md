# Phase 11 full-registry pilot log

Status: **clean first pilot day completed on 2026-09-25; STOP at Human checkpoint H12.**

Only 2026-09-25 has been covered. The same-day reruns below prove duplicate behavior but do not
count as another pilot day. The normal job-history database was preserved throughout. Return on a
later calendar day and say `run the next pilot scan` to continue the multi-day pilot.

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
- No normal pilot run restored, reset, or replaced the database. Checkpoint H7 was not triggered.

The local databases, reports, and backups remain ignored and must not be committed.

## Run chronology

All times below are Asia/Calcutta on 2026-09-25.

| Run | Profile | Time | Status | Sources success / empty / failed | Listings | New / duplicate-suppressed | Strict / uncertain / review | Duration |
|---|---:|---|---|---:|---:|---:|---:|---:|
| `scan-20260925T035057Z-f8166432` | `1.1.0` | 09:20:57–09:48:28 | complete | 84 / 2 / 0 | 26,116 | 45 / 282 | 4 / 4 / 52 | 1,650.665 s |
| `scan-20260925T042319Z-82cd2e17` | `1.1.1` | 09:53:19–17:36:14 | failed | stopped during source collection | — | — | — | 7 h 42 m 55 s |
| `scan-20260925T120833Z-f16f049a` | `1.1.1` | 17:38:33–18:41:08 | complete | 84 / 2 / 0 | 26,142 | 20 / 0 | 0 / 0 / 40 | 3,755.766 s |
| `scan-20260925T131248Z-a0c866e6` | `1.1.1` | 18:42:48–19:16:44 | complete rerun | 84 / 2 / 0 | 26,136 | 1 / 304 | 1 / 0 / 47 | 2,036.683 s |
| `scan-20260925T135115Z-dc5432db` | `1.1.2` | 19:21:15–20:12:49 | complete | 84 / 2 / 0 | 26,120 | 1 / 0 | 1 / 0 / 36 | 3,093.963 s |
| `scan-20260925T144452Z-39d54451` | `1.1.2` | 20:14:52–20:47:03 | complete rerun | 84 / 2 / 0 | 26,114 | 0 / 311 | 0 / 0 / 42 | 1,930.679 s |

The failed `1.1.1` attempt was durably closed as `failed`; it did not mutate job state because it
stopped before filtering and evaluation. It is retained in the chronology rather than being
silently discarded.

Ignored local report artifacts:

- `reports/phase11_pilot_2026-09-25.json`
- `reports/phase11_pilot_2026-09-25_postfix.json`
- `reports/phase11_pilot_2026-09-25_postfix_rerun.json`
- `reports/phase11_pilot_2026-09-25_postfix_v112.json`
- `reports/phase11_pilot_2026-09-25_v112_rerun.json`

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
  duplicates, and no repeated match.
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

## H12 stop decision

The first clean pilot day and the same-day duplicate check pass. Phase 11 is not yet complete
because only 2026-09-25 has been covered; the execution plan requires real scans on different
calendar days. Do not alter time, publication dates, or state to simulate another day.

**STOP — Human checkpoint H12.** Return on a later calendar day and say
`run the next pilot scan`. The next run must preserve `state/jobs.sqlite3`, verify the unchanged
configuration identifiers above, review every new match and source exception, update this log, and
commit the result.
