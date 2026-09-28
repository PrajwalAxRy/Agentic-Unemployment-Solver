# Phase 12 Package C cohort 3 validation

**Status: complete — 2 official deterministic sources activated.**

The user approved Packages A, B, and C on 2026-09-28. This third Package C cohort replaced stale
third-party registry sources for D. E. Shaw India and Squarepoint Capital with their official
inventories. D. E. Shaw India uses a new deterministic custom adapter. Squarepoint's official
careers JavaScript explicitly identifies its standard public Greenhouse board, so the existing
hardened Greenhouse adapter was reused instead of adding unnecessary company-specific code.
Packages D and E remain unapproved.

## Discovery and route selection

| Company | Rejected source | Official evidence | Selected route |
|---|---|---|---|
| D. E. Shaw India | Third-party Grapevine job copy | `https://www.deshawindia.com/careers` | Server-rendered Next.js `regularJobs` array |
| Squarepoint Capital | Third-party finance job page | `https://www.squarepoint-capital.com/open-opportunities` | Existing Greenhouse adapter, board token `squarepointcapital` |

D. E. Shaw India's official page embedded 78 unique public regular jobs and a separate 407-job
internal collection. The adapter contract emits only `regularJobs`; every live public row had a
matching top-level/data ID, title, office/location set, active-listing flag, canonical detail slug,
and complete description. Hyderabad, Bengaluru, and Gurugram were the only public locations. The
payload exposes no verified publication timestamp, so all dates remain explicitly `unknown`.

Squarepoint's official page loads
`https://boards-api.greenhouse.io/v1/boards/squarepointcapital/jobs?content=true`. The existing
Greenhouse adapter independently retrieved 88 unique jobs, including 24 with Bangalore/India
location evidence. All rows had complete descriptions and canonical official Squarepoint URLs.

## Implemented D. E. Shaw contract

`deshaw_india_index` requires the exact official careers URL, one expected Next.js data block, the
known careers page identifier, `jobsFetchingError=false`, and separate regular/internal arrays. It
checks public active status, positive stable IDs, title and office/location parity, ID-bearing
canonical slugs, non-empty descriptions, and duplicate identities. The fixture proves that the
internal collection is not emitted and covers valid empty, upstream fetch error, malformed job,
duplicate identity, redirect, and invalid configuration behavior.

## Activation and full-registry gates

| Company | Targeted production result | Required fields | Date result |
|---|---:|---:|---|
| D. E. Shaw India | 78 jobs, 1 page, 1 attempt | 0 missing | 78 unknown; no public publication field |
| Squarepoint Capital | 88 jobs, 1 page, 1 attempt | 0 missing | 84 published, 4 explicit updated-date fallbacks |

Registry version `0.3.0-phase12-c8` accounts for all 330 canonical companies:

- 121 enabled and 209 disabled records.
- 203 remaining `search_only` sources, four `unresolved`, and two approved `unsupported` sources.
- Eight enabled custom sources and 34 enabled Greenhouse sources.

The initial all-enabled sweep covered 121 sources and observed 37,431 jobs across 933 pages. It
recorded 116 successful, three verified empty, one suspicious, and one partial source. The sole
suspicious source was the unchanged Quantbox Research `stale_publication_dates` anomaly. Workday's
public board changed during the run and returned one malformed row after 376 jobs despite bounded
retries. An immediate isolated production retry completed on its second attempt with 379 jobs over
19 pages and zero missing fields. No parser change was made because the defect did not reproduce.

The effective final health disposition is **117 successful, three verified empty, one suspicious,
and no persistent failed, blocked, or partial source**, representing 37,434 jobs across 932 pages
after replacing the partial Workday observation with its complete retry.

Ruff formatting and linting passed, strict mypy passed across 102 source files, and the complete
pytest suite reported **541 passed**.

## Commits, rollback, and next step

- `4066604` adds the D. E. Shaw India custom adapter, fixture, focused tests, and runtime
  registration.
- `224052a` activates the official D. E. Shaw India and Squarepoint sources and updates registry
  accounting.

Reverting `224052a` returns both companies to disabled `search_only` records without removing the
reusable adapter code. This cohort is complete. Continue the approved Package C P1/P2
deterministic-source queue. Packages D and E still require explicit approval.
