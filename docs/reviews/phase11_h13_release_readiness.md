# Phase 11 H13 first-release readiness review

## Checkpoint status

**APPROVED — Human checkpoint H13 completed on 2026-09-28. The first release is approved and the
annotated `v0.1.0` tag is authorized.**

- Review date: 2026-09-28 (Asia/Calcutta)
- Release candidate: `job-finder 0.1.0`
- Proposed tag: `v0.1.0`
- Active source-registry version: `0.2.0-phase4`
- Search profile: `india-ai-ml-under-five-years` version `1.1.2`
- Seniority prompt: `1.0.1`
- State schema: `3`
- Report schema: `1`
- Python: CPython `3.12`
- Release recommendation: **approve the first release**
- H13 decision: the user replied `approve release, create tag v0.1.0`
- Release status: approved
- Tag status: approved and created from the validated release-decision commit

The approval accepts the explicit source exceptions and known limitations recorded below. It does
not expand first-release scope to scheduling, notifications, additional adapters, or lifecycle
tracking.

## Release-candidate identity

The final source activation is commit `d462aa976b4a16cdf69803c426c7cb03451a3f51`. The tracked
configuration hashes used by the final verifier and scan are:

- `config/company_sources.json`:
  `650863FB65733673819583DC4ECB664A1700A28108BA98C743313F2C31FF2119`;
- `config/search_profile.toml`:
  `84C9C8C091A15F9CEEF6F13EB058A41BFC205F13F2507F194DF39C87C142A604`;
- `config/seniority_prompt.toml`:
  `1DBD10716EADD2A3B2173556AA90A950A6C9CFE524034ED045EEECCB35FCCEB6`.

The search profile contains no temporary test value. A tracked-configuration scan found no API
key, password, client secret, or access-token assignment. Local provider credentials, state,
backups, reports, diagnostics, caches, and temporary files remain ignored and unstaged. The
provenance workbook is unchanged.

## Multi-day pilot evidence

Three clean calendar days satisfy the multi-day stability requirement:

| Date | Representative run | Source result | Duplicate / result evidence |
|---|---|---|---|
| 2026-09-25 | `scan-20260925T135115Z-dc5432db` | 84 success / 2 valid-empty / 0 failed | One valid strict match; profile `1.1.2` false-positive regressions absent |
| 2026-09-26 | `scan-20260926T000739Z-2cef6bde` | 84 success / 2 valid-empty / 0 failed | 0 new identities; 303 completed duplicates suppressed; no repeated match |
| 2026-09-28 | `scan-20260927T193726Z-8c89b1a8` | 84 success / 2 valid-empty / 0 failed | 1 new identity; 287 completed duplicates suppressed; no displayed match |

The unchanged immediate rerun on 2026-09-25 also found zero new identities, suppressed 311
completed duplicates, repeated no match, and used 169 cached decisions. The 2026-09-27 partial run
is retained as evidence that a genuinely moved source is reported as failed rather than empty; it
is not counted as a clean pilot day. H4 and H11 then governed the narrow Atomicwork repair.

## Final source verification and manual scan

The post-activation all-enabled verifier ran against all 86 enabled sources:

- 83 `success`, two valid `empty`, one reviewed `suspicious`, and zero `failed`;
- 26,118 jobs across 658 fetched pages;
- Deeptune and Rapido are the two verified empty sources;
- Quantbox Research is the only suspicious source, solely for the reviewed
  `stale_publication_dates` anomaly; and
- Atomicwork succeeded in one attempt with six jobs across two pages, zero missing required fields,
  and six explicit unknown dates.

The final preserved-state scan completed in 1,504.092 seconds:

- 330 canonical companies accounted for, 86 attempted, and 244 disabled or deferred;
- 84 successful sources, two valid-empty sources, and zero failed sources;
- 26,118 listings, 12,683 recency candidates, 1,247 role candidates, and 293 retained candidates;
- 293 observed identities, one new identity, and 287 completed duplicates suppressed;
- 23 location-review candidates, six description fetches, and four description failures;
- zero conditional passes and one deterministic conditional rejection;
- one live LLM evaluation, 164 cache hits, and one provider request;
- 1,013 measured input tokens, 285 measured output tokens, and 1,339 estimated input tokens;
- zero strict matches, zero uncertain-date matches, zero seniority matches, zero seniority
  rejections, and 28 seniority/review outcomes.

All 28 review rows were manually inspected: 21 `detail_location_unavailable`, four
`description_unavailable`, two `missing_location`, and one `seniority_uncertain`. The uncertainty
is supported by conflicting experience paths. The new Atomicwork Backend Engineer identity
`4062696008` was correctly rejected as `no_ai_topic`: its duties are conventional backend/platform
work, while AI appears only in the employer mission. No false positive, known false negative, or
unresolved systematic role/location defect was found.

## Release metrics

| Metric | Result | Evidence and disposition |
|---|---|---|
| Registry accounting | Pass | All 330 seed companies are accounted for: 86 enabled and 244 explicitly disabled, deferred, blocked, or unsupported with reasons. |
| Duplicate behavior | Pass | The unchanged immediate rerun displayed no repeated job; later clean days continued suppressing completed identities. |
| Role and location quality | Pass | Every final review row was inspected; two confirmed incidental-AI defects have regression examples; no systematic defect remains. |
| Seniority quality | Pass | H9-approved threshold and uncertainty policy remain in force; uncertain cases remain visible rather than being promoted. |
| Uncertainty | Pass | Unknown dates, unavailable descriptions, unresolved locations, provider failures, and seniority uncertainty have explicit report lanes. |
| Failure visibility | Pass | Atomicwork's move produced a visible failed/partial run, not a false empty result; Phase 10 failure drills and retry containment pass. |
| Operability | Pass | H10 approved the manual command and report; `docs/07_scan_runbook.md` and the repair runbook cover normal and degraded operation. |
| Repository quality | Pass | Ruff format/lint, strict mypy, and pytest pass; code, data, and documentation changes use focused commits. |

## Unresolved source exceptions

These exceptions are explicit and do not block the recommended first release:

- NVIDIA and PayPal are H4-approved unsupported Eightfold sources. Their official public careers
  pages are manual fallbacks; authentication and access controls were not bypassed.
- Of the 244 non-enabled companies, 238 remain `search_only`: 179 need future custom-adapter or
  deeper source-family work and 59 have conflicting, third-party, wrong-region, non-enumerating, or
  otherwise insufficient evidence. All retain a reason in canonical accounting.
- Moody's returning-applicant SuccessFactors login is not a valid inventory and remains an
  explicit custom-discovery item.
- Quantbox Research exposes eight current jobs whose `first_published` fields are old while
  `updated_at` remains current. It stays visible as `stale_publication_dates`; no date meaning is
  silently inferred.
- Atomicwork publication dates remain unknown. Some detail pages retain broken legacy Greenhouse
  Apply links, but the official same-origin detail pages remain the canonical readable URLs.
- SAP and SiMa.ai require bounded detail retrieval for date evidence because their listings omit
  usable publication dates. Their approved adapters and gates pass.
- JPMorganChase Oracle Cloud inventory can change while paginating and may return overlapping or
  short pages. Requested offsets, repeated pages, and unique identities remain checked visibly.

## Known product limitations

- This release is manually triggered. Scheduling and notifications remain deliberately deferred.
- The system automates 86 of 330 canonical companies. Disabled and unsupported companies are
  accounted for but do not contribute automated listings.
- Publication evidence is heterogeneous. All observed Lever, Workday, Darwinbox, Atomicwork, and
  some other records use an explicit uncertain or unknown basis under the H5-approved policy.
- Bank of America multi-location details can be unavailable and therefore produce visible
  location-review rows.
- Some SAP, SmartRecruiters, Freshworks, and other public pages expose no usable full description;
  those candidates remain review items instead of inferred matches.
- The AMD LLM gateway can intermittently return no completion text. These outcomes remain visible
  and retryable; they are never promoted to a match.
- Seniority is evaluated only after deterministic filters. Conflicting or insufficient experience
  evidence remains `seniority_uncertain`.
- Duplicate persistence models observed identities and completed decisions; it does not yet model
  closure, reopening, or repost lifecycle events.

## State safety and final repository checks

The final scan used the preserved schema-3 database. Immediately beforehand, all 394 records were
backed up and restore-verified at:

- `state/backups/phase11_2026-09-28_post_atomicwork_pre_scan.sqlite3`;
- `state/backups/phase11_2026-09-28_post_atomicwork_pre_scan_restore_check.sqlite3`.

The scan left 395 records: 21 pending, 196 completed, and 178 failed. No reset, replacement,
identity migration, or destructive operation occurred. The backup and restore check passed.

Final checks pass:

- targeted Atomicwork verification;
- complete affected Greenhouse/custom source-group verification;
- full all-enabled source verification;
- final manual full-registry scan and review;
- configuration-secret and temporary-value checks;
- Ruff format check and Ruff lint;
- strict mypy across 90 source files;
- complete pytest suite: 478 passed; and
- clean Git status at the H13 handoff, with no report, state, backup, secret, provenance workbook,
  or unrelated user file staged or modified.

## Release decision

The user approved the first release and creation of annotated tag `v0.1.0` on 2026-09-28. The
release metrics pass, the three clean pilot dates establish multi-day stability, the moved-source
workflow behaved safely, and the accepted limitations are visible and bounded. `v0.1.0` matches
the package version.

After this decision was recorded, the canonical validation suite was rerun, the release records
were committed, the working tree was confirmed clean, and the specifically authorized annotated
tag was created from that commit. Phase 11 and the first release are complete.
