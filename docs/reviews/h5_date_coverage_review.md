# H5 publication-date coverage review

## Checkpoint status

**Complete — Human checkpoint H5: option 4, the recommended hybrid policy, approved on 2026-09-22.**

Phase 5 listing, normalization, and date measurement completed on 2026-09-21. The search profile
used `measure_then_decide` to obtain this baseline. The approved profile is now `hybrid`; Phase 5
must rerun the complete registry report under that recorded policy before Phase 6 begins.

The complete sanitized runtime report is `reports/phase5_recency_measurement.json`. It is ignored by
Git and contains per-listing public URLs and date evidence, but no descriptions or response bodies.

## Run and health gate

- Registry: `0.2.0-phase4`; profile: `india-ai-ml-under-five-years` version `1.0.0`
- Scan completion: `2026-09-21T18:08:17+05:30`
- Inclusive timestamp boundary: `2026-09-11T18:08:17+05:30`
- Enabled companies: 86; outcomes: `{"empty": 2, "success": 84}`
- Observed listings: 26,122
- Valid identities: 26,122; valid canonical URLs: 26,122
- Invalid dates: 0; unassessed companies: 0
- First-seen timestamps available in this initial measurement: 0

Zeta Global needed one bounded whole-source retry after an intermittent invalid JSON response. The
final attempt passed with 145 listings. JPMorganChase's 7,000-plus-job Oracle inventory changed
during pagination; explicit oldest-first ordering, every requested offset, and unique-job retention
produced a healthy 7,372-job scan with visible `inventory_total_changed`, `short_page`, and
`duplicate_job_id` warnings. No access block was retried or bypassed.

## Company-level coverage

| Coverage class | Companies | Percent of 86 |
|---|---:|---:|
| Every observed listing reliable | 49 | 56.98% |
| Mixed reliable and uncertain | 5 | 5.81% |
| No reliable publication dates | 30 | 34.88% |
| Valid empty source | 2 | 2.33% |
| Unassessed | 0 | 0.00% |

The five mixed companies are AlphaGrep, Graviton Research Capital, SingleStore, Uber, and
JPMorganChase. AlphaGrep, Graviton, and SingleStore each have one Greenhouse `updated` fallback.
Uber has 20 and JPMorganChase has 219 date-only listings on the exact boundary date.

The 30 companies with no reliable list-date evidence are:

- Darwinbox: ClearTax, Porter, and Unacademy.
- Eightfold: Millennium Management.
- Jobvite: SiMa.ai.
- Lever: 100ms, Aera Technology, BarRaiser, Bazaarvoice, Dozee, Doxel, Level AI, Neuron7.ai,
  Paytm, RapidAI, and Safe Security.
- SuccessFactors: SAP.
- Workday: Analog Devices, Bank of America, Barclays, Cadence, CrowdStrike, Fractal Analytics,
  London Stock Exchange Group, Nasdaq, NXP Semiconductors, Palo Alto Networks, Uniphore, Visa,
  and Workday.

Deeptune and Rapido are the two valid empty sources.

## Listing-level coverage and ten-day decisions

| Evidence state | Listings | Percent of 26,122 |
|---|---:|---:|
| Reliable publication evidence | 15,911 | 60.91% |
| Uncertain value | 10,146 | 38.84% |
| Invalid value | 0 | 0.00% |
| Missing value | 65 | 0.25% |

| Interim decision | Listings | Percent of 26,122 |
|---|---:|---:|
| Inside ten-day window | 2,326 | 8.90% |
| Outside ten-day window | 13,585 | 52.01% |
| Measurement pool, no age decision | 10,211 | 39.09% |
| Invalid | 0 | 0.00% |

Only verified `published` evidence receives an inside/outside decision. The 10,211-item measurement
pool is the 10,146 uncertain values plus 65 missing values. Nothing in that pool currently passes or
fails the age gate.

## Adapter breakdown

| Adapter | Companies | Listings | Reliable | Uncertain | Missing | Inside | Outside | No age decision | Company classes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Ashby | 25 | 1,028 | 1,028 | 0 | 0 | 105 | 923 | 0 | 24 reliable, 1 empty |
| Darwinbox | 4 | 141 | 0 | 141 | 0 | 0 | 0 | 141 | 3 no-reliable, 1 empty |
| Eightfold | 1 | 225 | 0 | 225 | 0 | 0 | 0 | 225 | 1 no-reliable |
| Greenhouse | 25 | 2,270 | 2,267 | 3 | 0 | 215 | 2,052 | 3 | 22 reliable, 3 mixed |
| Jobvite | 1 | 18 | 0 | 0 | 18 | 0 | 0 | 18 | 1 no-reliable |
| Lever | 11 | 372 | 0 | 372 | 0 | 0 | 0 | 372 | 11 no-reliable |
| Oracle Cloud | 2 | 7,911 | 7,672 | 239 | 0 | 1,404 | 6,268 | 239 | 2 mixed |
| SmartRecruiters | 3 | 4,944 | 4,944 | 0 | 0 | 602 | 4,342 | 0 | 3 reliable |
| SuccessFactors | 1 | 47 | 0 | 0 | 47 | 0 | 0 | 47 | 1 no-reliable |
| Workday | 13 | 9,166 | 0 | 9,166 | 0 | 0 | 0 | 9,166 | 13 no-reliable |

Every adapter has zero invalid dates. Each table's evidence and decision columns reconcile to its
listing count.

## Representative evidence reviewed

Reliable examples were checked on both sides of the boundary:

| Family | Raw source value | Interpretation | Public job |
|---|---|---|---|
| Ashby | `2026-09-15T14:22:37.185+00:00` | Reliable, inside | [Harvey](https://jobs.ashbyhq.com/harvey/c34ee114-fd2d-4507-9888-711397e037bd) |
| Ashby | `2026-02-25T09:45:38.623+00:00` | Reliable, outside | [Harvey older listing](https://jobs.ashbyhq.com/harvey/e04146f6-f79a-4023-9523-fe691038b330) |
| Greenhouse | `2026-09-18T11:42:03-04:00` | Offset preserved, inside | [Glean](https://job-boards.greenhouse.io/gleanwork/jobs/4735493005) |
| Oracle Cloud | `2026-09-18` | Date precision preserved, inside | [Uber](https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/UberCareers/job/147707) |
| Oracle Cloud | `2026-09-09` | Date precision preserved, outside | [Uber older listing](https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/UberCareers/job/147313) |
| SmartRecruiters | `2026-09-21T12:35:37.432Z` | UTC instant, inside | [Bosch](https://jobs.smartrecruiters.com/BoschGroup/744000150679197) |
| SmartRecruiters | `2016-03-29T07:40:46.000Z` | Reliable ancient value, outside | [Entropik](https://jobs.smartrecruiters.com/Entropik/90975178) |

Representative uncertainty patterns are:

| Pattern | Raw / normalized evidence | Interpretation | Public job |
|---|---|---|---|
| Darwinbox epoch | `1777401000` / `2026-04-28T18:30:00+00:00` | Field meaning is not verified publication time | [ClearTax](https://clear.darwinbox.in/ms/candidate/careers/a69f1db303413c) |
| Eightfold epoch | `1788998400` / `2026-09-10T00:00:00+00:00` | `t_create` meaning is unverified | [Millennium](https://mlp.eightfold.ai/careers/job/755958684099) |
| Greenhouse update fallback | `2025-12-29T00:20:56-05:00` | Explicitly `updated`, never relabelled published | [AlphaGrep](https://job-boards.greenhouse.io/alphagrepsecurities/jobs/4116484002) |
| Jobvite list omission | no value | Detail pages can supply `datePosted` only after pre-detail filters | [SiMa.ai](https://jobs.jobvite.com/simaai/job/oI18zfwa) |
| Lever epoch | `1780033912155` / `2026-05-29T05:51:52.155000+00:00` | `createdAt` meaning is unverified | [Doxel](https://jobs.lever.co/doxel/51ac8464-6e95-4275-af44-718c933b2374) |
| Date-only boundary | `2026-09-11` | Could fall before or after the exact `18:08:17` boundary | [Uber](https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/UberCareers/job/149191) |
| SuccessFactors list omission | no value | Detail pages can supply schema.org `datePosted` after pre-detail filters | [SAP](https://jobs.sap.com/job/Bangalore-Technical-Product-Manager-%28mfd%29-for-API-Management-%40-BTP-Integration-Suite-560066/1280449101/) |
| Workday relative label | `Posted 3 Days Ago` | Relative and unverified; exact publication instant is unavailable | [Uniphore](https://uniphore.wd503.myworkdayjobs.com/Uniphore/job/USA---CA---Palo-Alto/Senior-Sales-Engineer_JR101211) |

Direct pages that render server-readable content matched the normalized identity and visible job.
Some JavaScript-hosted direct pages do not render in the available text browser, but their public
adapter resources and direct HTTP links passed the Phase 4 family checks. No publication meaning was
promoted based only on a numeric or relative value.

## First-seen availability and limitation

`first_seen_at` is unavailable for all 26,122 listings because persistence begins in Phase 6. A
future persisted first observation can support forward-only aging, but it cannot prove the original
age of any listing already present in this baseline. Treating this baseline's uncertain jobs as
newly published would be incorrect.

## Options and recommendation

1. **Exclude uncertain-date jobs from strict ten-day results.** This is strict, but immediately
   hides 10,211 listings (39.09%), including every observed listing from 30 companies.
2. **Include them in a separate uncertain-date section.** This preserves coverage and semantic
   honesty, but old uncertain jobs can recur indefinitely without a forward-aging rule.
3. **Use `first_seen` for forward-only recency after the initial baseline.** This becomes useful
   after persistence exists, but cannot classify the initial 10,211-item pool historically.
4. **Apply a documented hybrid policy by adapter or evidence type.**

**Recommendation: option 4.** Use verified publication timestamps for the strict ten-day section;
keep date-only boundary overlaps and `updated` fallbacks in a separate uncertain section; fetch
Jobvite and SuccessFactors detail dates only after deterministic title and India-location filters;
and keep Workday, Lever, Darwinbox, and Eightfold jobs in the uncertain section while recording
`first_seen` for forward-only aging on later runs. The initial baseline must remain explicitly
uncertain. This retains material company coverage without pretending that observation time or an
unverified source field is publication time.

## Decision recorded

The user approved option 4, including the recommended hybrid policy, on 2026-09-22. The decision
is represented by search-profile version `1.1.0`; its fixtures and boundary tests cover updated
dates and forward-only `first_seen` aging. The post-decision full-registry validation is recorded
below once completed.
