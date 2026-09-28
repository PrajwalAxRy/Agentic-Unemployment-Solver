# Phase 12 Package B validation

**Status: complete — 6 reusable-family sources activated; 8 candidates failed closed.**

The user approved Packages A, B, and C on 2026-09-28. Package B assessed all 14 companies
assigned to the new reusable-family (`NF`) route. Four reusable adapters were added, one existing
adapter was extended, and no Package D endpoint replay or Package E fallback was activated.

## Activated sources

| Adapter | Companies | Live outcome |
|---|---|---|
| Freshteam | Locus; Jio Platforms / Haptik | 9 and 16 jobs; all 25 public details validated |
| Rippling | Sanas | 7 jobs; all 7 public details validated |
| SuccessFactors | PayU | 130 jobs over 6 pages; first, middle, and last details validated |
| SenseHQ | Groww | 17 jobs; 16 listing descriptions plus one explicit source-empty description |
| Recruiterflow | CoinSwitch | 6 jobs; all 6 public details and `datePosted` values validated |

The activated cohort accounts for 185 current listings. Freshteam, Rippling, SenseHQ, and
Recruiterflow now have independent fixture suites, bounded public collection contracts, stable
identity checks, explicit date semantics, and runtime registration. PayU's official India site
proved a current branded SuccessFactors category; a saved regression extended the existing
SuccessFactors path validator without weakening its host and category checks.

Recruiterflow repeats jobs under department, group, and location views. The adapter uses the
department view once and requires all three unique-ID sets to agree before it declares the
inventory complete. CoinSwitch passed that cross-check and every one of its six JSON-LD detail
pages supplied a full description and publication date.

Creation timestamps from Rippling and SenseHQ are retained as `unknown`; they are not promoted to
publication dates. Freshteam, SuccessFactors, and Recruiterflow publication dates are read from
public detail-page `datePosted` evidence. Groww's one empty description remains visible and
measured rather than being silently discarded.

## Candidates left disabled

| Company | Observed gate failure | Disposition |
|---|---|---|
| Adobe | The official Phenom site did not expose an independently replayed complete collection contract. Indexed SmartRecruiters and Trakstar candidates were not proven to be the current official inventory. | Keep `search_only`; require Package D public-endpoint replay before selecting an adapter. |
| Navi | The official careers page links to a TurboHire board with an organization ID, but its public JavaScript shell did not establish a stable, session-free complete listing request. | Keep `search_only`; move the public request replay to Package D. |
| Binocs | The public Notion page did not provide a stable, independently replayable collection whose completeness and job identities could be tested. | Keep `search_only`; reconsider only with deterministic enumeration evidence. |
| LimeChat | The Zoho Recruit URL returned a JavaScript shell without a proved inventory, while the current official Notion careers page showed an Open Positions section without enumerated roles. Zero could not be distinguished from an incomplete shell. | Keep `search_only`; Package D may replay a public endpoint, or Package E may review an explicit-empty monitor. |
| Nektar AI | The saved `/llm-info/` URL is not a job inventory, the earlier Coda route was not re-established, and current search results introduced a different-company identity collision. | Keep `search_only`; identity-safe rediscovery belongs to Package E. |
| NeuralGarage | The PyjamaHR page exposed company metadata but no jobs and no explicit complete empty-state contract. | Keep `search_only`; do not treat the shell as a valid empty board. |
| GreyOrange | The saved URL is a contact page, and no current official complete hosted-board mapping was independently established; third-party careers-intelligence results were rejected. | Keep `search_only`; require identity-safe official evidence before implementation. |
| ideaForge | The official page exposed a Join Us call to action but no stable server-rendered collection or independently replayed public listing endpoint. | Keep `search_only`; queue only the public endpoint investigation for Package D. |

These eight results are not counted as healthy empty sources. They remain in the canonical
330-company accounting with explicit evidence and require the separately unapproved Package D or
E work indicated above.

## Full-registry gate

Registry version `0.3.0-phase12-b5` accounts for all 330 canonical companies:

- 113 enabled sources and 217 disabled/backlog or unsupported records.
- 211 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- Adapter outcomes across all 113 enabled sources: 109 successful, three verified empty, one
  suspicious, zero failed, zero blocked, and zero partial.
- 32,379 observed listings over 880 fetched pages.
- Date evidence: 18,737 published, three updated, and 13,639 unknown under the approved hybrid
  policy.
- Every Package B source succeeded. Their live listing counts were Sanas 7, Locus 9, PayU 130,
  CoinSwitch 6, Groww 17, and Haptik 16.
- The sole suspicious source remains the pre-existing, reviewed Quantbox Research
  stale-publication-date anomaly.

The all-enabled verifier exits nonzero because it correctly keeps the Quantbox anomaly visible.
Package B introduced no new failed, blocked, partial, suspicious, or incomplete source.

Formatting, lint, strict mypy, and the complete test suite passed; pytest reported **502 passed**.

## Rollback

Each adapter implementation and source activation is in a focused commit. Reverting an activation
returns that company to its prior `search_only` configuration without requiring an adapter-code
rollback. The SuccessFactors branded-path extension is independently reversible.

## Next step

Package B is complete. Continue with approved Package C, implementing deterministic custom
sources in small P1/P2 cohorts before P3. Packages D and E remain unapproved.
