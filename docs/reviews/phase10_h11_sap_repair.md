# Phase 10 SAP source repair review

## Checkpoint status

**APPROVED — Human checkpoint H11 completed on 2026-09-25.**

- Proposal ID: `repair-1ddc97abb012ee26`
- Proposal status: `approved and applied`
- Affected company: SAP only (`company_id=sap`)
- Change type: `source_url`
- Confidence: high
- Decision: the user replied `approve repair-1ddc97abb012ee26`.
- Repair commit: `4c4b2c8` (`data: repair SAP source host`)

The repair tooling did not activate the proposal. The exact reviewed diff was applied through the
normal configuration workflow after approval and pinned by a registry regression.

## Observed failure

The active SAP source uses the official category URL on `jobs.sap.com`. That host now serves SAP's
new Next.js careers site to the truthful bounded client instead of the SuccessFactors listing
structure expected by the configured adapter. The all-enabled verifier made three bounded
attempts and recorded:

- Outcome `failed`; completeness `false`; zero parsed jobs from one response page.
- Diagnostic `unsupported_schema`; failure category `schema_change`.
- No response body, description, exception message, cookie, credential, or session value in the
  saved report or repair request.

SAP's official `careers.sap.com` host still serves the identical India category path as public
SuccessFactors inventory. No authentication, CAPTCHA bypass, session reuse, or access-control
workaround is involved.

## Exact approved diff

```diff
- "careers_url": "https://jobs.sap.com/go/SAP-Jobs-in-India/851201/"
+ "careers_url": "https://careers.sap.com/go/SAP-Jobs-in-India/851201/"

- "host": "jobs.sap.com"
+ "host": "careers.sap.com"
```

No adapter code, category path, identity strategy, date strategy, detail strategy, enablement,
company coverage, or job-history state changes.

## Fixture and automated evidence

- Existing SuccessFactors tests cover healthy listings, empty inventory, malformed pages, access
  blocks, pagination, duplicates, and public detail parsing.
- Phase 10 drills cover login/CAPTCHA pages, missing fields, content-type changes, repeated pages,
  timeout, rate limiting, count collapse, peer isolation, future dates, LLM unavailability, and
  state-lock contention.
- The immutable proposal-preview tests prove that testing does not mutate the active registry and
  that a stale `before` value fails closed.
- Repository validation passes with Ruff formatting, Ruff lint, strict mypy, and 461 tests.

## Live evidence

The exact validated proposal was overlaid in memory and tested with the normal SuccessFactors
adapter and bounded truthful HTTP client. It produced:

- Outcome `success`; completeness `true`; 47 unique jobs across two pages in one attempt.
- Stable numeric requisition IDs, titles, locations, and direct public job links.
- All 47 list rows explicitly retain `unknown` date evidence because the list page omits a
  publication date; the approved detail strategy remains responsible for `datePosted`.
- A representative public detail for requisition `1280449101` matched the listing identity and
  exposed the title, Bangalore location, schema.org `datePosted`, and a substantive description.

The proposal artifacts are ignored local diagnostics:

- `diagnostics/repair_requests/sap.json`
- `diagnostics/repair_proposals/sap.validated.json`
- `reports/phase10_sap_proposal_verification.json`

After approval, the active mapping passed targeted SAP and complete SuccessFactors verification
with 48 jobs across two pages, complete in one attempt, and no failure or anomaly. The increase
from 47 to 48 is normal live-inventory movement and does not change the reviewed source mapping.

## Full-registry review

The first pre-repair all-enabled run accounted for all 86 enabled companies: 82 succeeded, two
were valid empty inventories, SAP was the sole failed source, and Quantbox Research was the sole
suspicious source. Quantbox's eight public listings have old `first_published` dates even though
their `updated_at` values remain current. Direct inspection confirmed that condition is real
source data, so it stays visible as a reviewed date anomaly and is not part of this repair.

A second all-enabled run exercised the corrected anomaly classifier and new progress output. It
confirmed Quantbox as `suspicious` with `stale_publication_dates` and no false failure category.
After 63 successes, one valid empty result, and that anomaly, host connectivity failed across 21
consecutive sources on unrelated domains and adapter families. Every affected record remained
visible as `temporary_availability`; none appeared healthy or empty. Immediate fresh-process
checks recovered Clipboard Health (Ashby, 36 jobs), Endor Labs (Greenhouse, 27 jobs), Freshworks
(SmartRecruiters, 125 jobs on two pages), and Rapido (Darwinbox, valid empty). A fresh SAP check
also reached the host and reproduced `unsupported_schema`. This establishes an external transient
rather than 21 simultaneous source regressions and does not change the SAP repair scope.

Healthy sources remain usable when a peer fails. The verifier writes every record and returns a
nonzero status without changing job history or active configuration.

The final post-repair all-enabled verification accounted for all 86 enabled companies and 26,193
jobs across 660 pages: 83 sources succeeded, two were valid empty inventories, and Quantbox was
the one reviewed suspicious source. There were zero failure categories. SAP succeeded with 48
jobs across two pages and no anomaly.

## Rollback

If the approved host later fails validation, revert only SAP's `careers_url` and
`adapter_parameters.host` to `jobs.sap.com`, then rerun targeted SAP, complete SuccessFactors, and
all-enabled verification. The parent of repair commit `4c4b2c8` retains the two old values, so
rollback remains exact and recoverable.

## Decision record

H11 authorized only the two reviewed SAP field changes. Those changes were applied normally,
regression-tested, validated against SAP, the complete SuccessFactors group, and all enabled
sources, and committed as a focused repair. No adapter code, other company configuration, or
job-history state changed.
