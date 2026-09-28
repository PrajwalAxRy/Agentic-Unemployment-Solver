# Phase 12 Package A validation

**Status: complete — 21 existing-adapter sources activated; 13 candidates failed closed.**

The user approved Packages A, B, and C on 2026-09-28. Package A reused only existing, tested
adapter families. No Package D endpoint replay or Package E fallback was activated.

## Activated sources

| Adapter | Companies | Live outcome |
|---|---|---|
| Greenhouse | Rubrik, Cockroach Labs, FalconX, Okta, NK Securities, AQR Capital Management, Coinbase, Compass, Crunchyroll | Eight successful; Compass verified empty |
| Workday | Slack, Broadcom, Quantiphi, Mastercard, KLA, Marvell, Aptiv, BrowserStack | Eight successful |
| Lever | CRED | Successful |
| Ashby | TestGorilla | Successful |
| Oracle Cloud | Texas Instruments | Successful |
| SmartRecruiters | Renesas | Successful after the structured-description regression fix |

Targeted Package A validation accounted for 6,113 current listings over 209 fetched pages. Every
activated source had a complete public inventory outcome, stable identifiers and canonical URLs,
zero listing-parser failures, and the approved date treatment for its adapter family. Adapters with
separate details passed a representative public detail request; listing-payload adapters supplied
their descriptions with the listing.

The Renesas detail check exposed a current SmartRecruiters schema in which each `jobAd.sections`
value is an object containing HTML in `text`. A regression test reproduced the missing-description
failure. The shared parser now accepts both legacy strings and structured sections, strips HTML,
and preserves paragraph separation. The focused test and the live 902-listing Renesas revalidation
passed before registry activation.

## Candidates left disabled

| Company | Observed gate failure | Disposition |
|---|---|---|
| Salesforce | The live inventory changed during pagination and exceeded the first-page total. | Keep `search_only`; retry the Workday candidate in a later cohort. |
| Qualcomm | The proposed Workday API returned zero while a current public job page existed. | Keep `search_only`; the result is not a defensible empty board. |
| Navan | Proposed Greenhouse board returned HTTP 404. | Rediscover the current official inventory. |
| Opendoor | Proposed Greenhouse board returned HTTP 404 despite stale indexed job pages. | Rediscover the current official inventory. |
| ThoughtSpot | Proposed Greenhouse board returned HTTP 404. | Rediscover the current official inventory. |
| Oracle / OCI | No independently verified Oracle Cloud host and site number. | Keep disabled pending deterministic parameter evidence. |
| American Express | The vanity careers URL did not establish a replayable Oracle Cloud host. | Keep disabled pending deterministic parameter evidence. |
| Lam Research | The current official inventory no longer proved the proposed Workday mapping. | Reclassify for an approved custom/new-family cohort. |
| Nutanix | The current official inventory did not prove the proposed Workday mapping. | Reclassify for an approved custom/new-family cohort. |
| Synopsys | The current official search is not the proposed Workday board. | Reclassify for an approved custom cohort. |
| Eightfold AI | Its shared `app.eightfold.ai` host requires explicit company-domain handling not supported by the existing tenant adapter. | Keep disabled; treat as a reusable-adapter extension candidate. |
| Morgan Stanley | The existing Eightfold JSON route returned HTTP 403 without authentication. | Keep disabled; do not bypass the access control. |
| Games24x7 | The proposed Darwinbox route returned HTTP 404; the official site now exposes a different careers surface. | Reclassify for an approved custom cohort. |

These 13 failures do not become healthy empty sources and do not count as Package A activations.

## Full-registry gate

Registry version `0.3.0-phase12-a1` accounts for all 330 canonical companies:

- 107 enabled sources and 223 disabled/backlog or unsupported records.
- 217 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- Adapter outcomes across all 107 enabled sources: 103 successful, three verified empty, one
  suspicious, zero failed, zero blocked, and zero partial.
- 32,198 observed listings over 867 fetched pages.
- Date evidence: 18,741 published, three updated, and 13,454 unknown under the approved hybrid
  policy.
- The sole suspicious source is the pre-existing, reviewed Quantbox Research stale-publication-date
  anomaly. No Package A source was failed, blocked, partial, or suspicious.

The full verifier exits nonzero because it correctly keeps that known Quantbox anomaly visible.
Package A introduced no new full-registry failure category.

## Rollback

Revert the Package A registry commit to return the 21 records to their prior `search_only` state.
The SmartRecruiters parser fix is independently reversible and does not require registry rollback.

## Next step

Package A is complete. Continue with approved Package B reusable-family adapters. Package D and
Package E remain unapproved.
