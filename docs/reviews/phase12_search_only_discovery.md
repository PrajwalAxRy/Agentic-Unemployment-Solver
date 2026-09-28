# Phase 12 search-only source discovery

## Status

Stages 1–7 are complete for the 238 companies whose release registry entry uses
`search_only`. This discovery result did not change the 86 enabled sources, the four `unresolved`
records, the two H4-approved `unsupported` records, runtime dispatch, or the `v0.1.0` release
baseline.

The user approved Packages A, B, and C on 2026-09-28. Package C approval covers all priorities,
with P1/P2 implemented before P3. On 2026-09-29 the user approved continuing through the remaining
companies and then evaluating Packages D and E. The existing public-source, no-bypass,
completeness, and fail-closed gates remain mandatory. Implementation evidence and registry changes
are recorded in separate package/cohort review artifacts.

Package A is complete. Twenty-one candidates passed their activation gates and 13 failed closed;
see `phase12_package_a_validation.md`. Package B is also complete: six reusable-family sources
were activated and eight candidates failed closed; see `phase12_package_b_validation.md`.
Package C is active. Its first cohort activated Amazon / AWS, Google, and Apple. Microsoft's custom
adapter was implemented and validated in isolation, but the source remains disabled after the final
production command hit the upstream rolling request quota; see
`phase12_package_c_cohort1_validation.md`. Cohort 2 activated Stripe, ServiceNow, and Coupang while
Flipkart failed closed; cohort 3 activated official deterministic sources for D. E. Shaw India and
Squarepoint Capital; cohort 4 activated Altimate.ai, Aganitha, GalaxEye, and Gnani.ai; and cohort 5
activated Atlassian, GitLab, Qure.ai, and Airbnb while LinkedIn failed closed; cohort 6 activated
Intuit, Twilio, Meesho, PhonePe, Swiggy, and Tower Research Capital while Roku failed closed; and
cohort 7 activated Salesforce, Moloco, InMobi, Postman, TrueFoundry, Booking.com, Navi, and
Quadeye. See
`phase12_package_c_cohort2_validation.md`, `phase12_package_c_cohort3_validation.md`,
`phase12_package_c_cohort4_validation.md`, `phase12_package_c_cohort5_validation.md`,
`phase12_package_c_cohort6_validation.md`, and `phase12_package_c_cohort7_validation.md`.

## Frozen baseline and accounting

- Baseline commit: `7818f8bbb7cf4871af769e5ad60ae220c2a1d5e2` (`v0.1.0`).
- Registry: `config/company_sources.json`.
- Search-only records: 238 unique companies: 53 P1, 82 P2, and 103 P3.
- Starting discovery confidence: 178 medium and 60 low.
- Final decision rows: 238. The company-by-company ledger is in
  `docs/reviews/phase12_search_only_company_dossiers.md`.
- Registry mutations in Stages 1–7: zero.

| State | Count |
|---|---:|
| Browser-reviewed and assigned a plan | 238 |
| Missing decision row | 0 |
| Runtime sources activated | 0 |
| Total | 238 |

### Final route distribution

| Route | Count |
|---|---:|
| Existing adapter (`EA`) | 34 |
| New reusable family (`NF`) | 14 |
| Deterministic custom adapter (`CA`) | 114 |
| Endpoint replay required (`RD`) | 35 |
| Verified-empty monitor (`TE`) | 4 |
| Monitored/manual discovery (`ME`) | 18 |
| Identity-safe rediscovery (`RS`) | 19 |
| Total | 238 |

## What was done

1. Froze and reconciled the 238-record manifest against the release registry.
2. Re-ran bounded public-source probes for all saved proposals. The conflict cohort included 59
   search-only companies plus four separate unresolved records; the auto-verified cohort covered
   all 178 medium-confidence search-only records.
3. Opened every search-only careers source in the ChatGPT browser, checking ownership, redirects,
   visible job inventory, filters, pagination, detail behavior, and obvious identity collisions.
4. Refreshed hosted-ATS fingerprints for all 178 reachable medium-confidence pages. Sixteen pages
   exposed ATS signals; ambiguous/internal-only signals were not treated as approved mappings.
5. Re-searched the remaining low-confidence or conflicting companies and corrected obvious bad
   identities and stale links with public evidence.
6. Assigned every company an implementation route, concrete next action, evidence confidence, and
   risk note.
7. Consolidated the routes into implementation packages below.

The browser available to this run exposed rendered page structure, links, and public page content,
but not a durable pixel-screenshot or DevTools-network export channel. Therefore no screenshot or
HAR artifact is claimed. Where the DOM/browser view could not prove the underlying endpoint, the
ledger explicitly says `replay required`; this is preferable to inventing an endpoint from a UI.
The ignored `diagnostics/phase12_*` probe and fingerprint files remain local evidence and are not
release artifacts.

## Important corrections discovered

- Zerodha's saved URL belongs to Zerodha Fund House. The official Zerodha careers page is
  `https://careers.zerodha.com/` and currently presents a valid empty state.
- Google's current official search is
  `https://www.google.com/about/careers/applications/jobs/results`.
- Amazon/AWS jobs resolve through the public `amazon.jobs` inventory.
- Salesforce and Slack expose Salesforce Workday boards; Qualcomm, Quantiphi, Mastercard,
  Marvell, BrowserStack, and KLA also have strong Workday candidates.
- NK Securities exposes an official Greenhouse board; CRED exposes Lever; TestGorilla exposes
  Ashby; Morgan Stanley exposes Eightfold; American Express and Texas Instruments expose Oracle
  Cloud; Games24x7 exposes Darwinbox.
- Sanas links to Rippling ATS. Locus and Haptik link to Freshteam. CoinSwitch links to
  Recruiterflow. Groww uses SenseHQ. Navi links to TurboHire. LimeChat uses Zoho Recruit.
- Apna, Ather Energy, MediaTek, MongoDB, Squarepoint, and Mercedes-Benz R&D India expose usable
  current official inventories and are good deterministic custom-adapter candidates.
- `slice.careers` is the wrong company: it belongs to a US restaurant-software business, not the
  Indian fintech in the seed. The saved sources for X, Samsung R&D, Portkey, Jupiter, Myntra,
  Western Digital/SanDisk, Udaan, and several small AI companies also need identity-safe
  replacement rather than adaptation as-is.
- Noon, Maxim AI, Zerodha, and Ripik.AI displayed defensible current empty states. Empty-page
  monitoring still needs a deterministic completeness contract before activation.

## Disposition vocabulary

The ledger uses these routes:

| Code | Meaning |
|---|---|
| `EA` | Reuse an existing adapter after tenant/token and full-company validation. |
| `NF` | Build one reusable adapter for a newly observed hosted family. |
| `CA` | Build a deterministic company-specific adapter from public HTML/JSON. |
| `RD` | Official inventory found, but endpoint/detail replay must be completed before selecting `EA`, `NF`, or `CA`. |
| `TE` | Current official page is a defensible empty state; implement an empty-state monitor and completeness test. |
| `ME` | No official enumerating inventory was found; retain a monitored/manual discovery fallback. |
| `RS` | Saved evidence is stale, third-party, or the wrong company; rediscover identity-safe official evidence first. |

`ME`, `RS`, and `RD` are not approvals for an LLM runtime scraper. The LLM/browser remains a
discovery and exception-analysis tool. Routine collection should become deterministic whenever a
public, replayable mechanism exists.

## Recommended implementation packages

### Package A — existing adapters first

Implement and fully validate the high-confidence `EA` rows first. They use already tested adapter
contracts and give the best coverage-to-risk ratio. Each source still needs official ownership,
tenant/token, India coverage, pagination, detail, identity, and date validation before enablement.

### Package B — reusable hosted families

Add small, independently tested adapters for Phenom, Rippling ATS, Freshteam, Zoho Recruit,
Recruiterflow, SenseHQ, TurboHire, and public Coda/Notion-style boards where stable enumeration can
be proven. Consider iCIMS and Zappyhire only after a public external-board endpoint is replayed;
internal candidate/login links are insufficient.

### Package C — high-value deterministic custom sources

Implement P1 and P2 `CA` sources in small cohorts, starting with Google, Microsoft, Amazon Jobs,
Apple, LinkedIn, Stripe, ServiceNow, Coupang, Flipkart, D. E. Shaw India, Squarepoint, Apna, Ather,
MediaTek, MongoDB, and Mercedes-Benz. Every adapter needs fixtures, pagination limits, stable IDs,
detail retrieval, date evidence, and a full-company live validation before activation.

### Package D — endpoint replay queue

For `RD` rows, use an interactive browser with network inspection to capture only public requests,
then independently replay them without cookies or browser state. Promote each successful result to
`EA`, `NF`, or `CA`; otherwise move it to `ME` with the failure recorded. This package is deliberately
separate so uncertain fingerprints cannot silently become production mappings.

### Package E — empty, manual, and identity-repair lanes

- `TE`: monitor the official page and prove that zero means zero before activation.
- `ME`: keep the company in accounting, run bounded periodic discovery, and surface the lack of a
  public inventory. Do not fabricate listings from generic company pages.
- `RS`: correct the company identity/source first. Do not implement the currently saved URL.

An API-backed LLM browser adapter remains a last-resort exception for `ME` sources only. It should
emit the same evidence schema, operate under strict request/page/cost limits, never bypass access
controls, and remain visibly lower-confidence than deterministic adapters.

## Validation and activation rules

Every implementation package must preserve the existing order of operations:

```text
deterministic listing discovery
    -> deterministic role and India-location filters
    -> full-description retrieval
    -> deterministic substantive-AI-work check
    -> LLM seniority evaluation
    -> match / reject / uncertain report
```

Before any source is enabled, require adapter fixtures, focused tests, an independent public replay,
representative detail checks, bounded full-company validation, date-coverage measurement, and a
registry diff review. A successful HTTP response alone is not evidence of complete job inventory.

## Human checkpoint disposition

Approved on 2026-09-28: Package A, Package B, and Package C (all priorities, implemented P1/P2
before P3). Approved on 2026-09-29: continue the remaining companies and evaluate Package D and
Package E. Approval does not waive any source-identity, completeness, validation, access-control,
or human-checkpoint requirement.
