# Phase 12 Package C cohort 9 validation

## Scope

This cohort activates Index Exchange from its official careers opportunities page and S&P Global
from its officially linked Workday tenant. Browser
inspection was used only to understand the third-party Gem detail rendering. Production uses
bounded direct HTTP: the official page is the authoritative inventory and Gem's public HTML
metadata supplies deferred descriptions.

## Evidence and result

- Official inventory: `https://www.indexexchange.com/careers/opportunities/`
- Public detail host: `https://jobs.gem.com/index-exchange/...`
- The live gate passed on its first attempt with 30 declared table rows and 29 unique jobs.
- One external ID appears twice for Toronto and New York. The rows have identical title,
  department, URL, and ID, so the adapter deterministically merges their locations.
- Three current jobs are in Bengaluru.
- Representative Gem details returned matching titles and canonical URLs with 7,595 and 7,469
  normalized description characters.
- No verified publication timestamp is exposed by the authoritative listing, so dates remain
  explicitly unknown.
- S&P Global passed on its first attempt with 270 unique jobs across 14 Workday pages. First,
  middle, and final details returned 8,535, 9,493, and 8,024 normalized description characters.
  Workday's relative `postedOn` values remain unknown-basis evidence.

## Safety and completeness controls

- The parser requires the official table marker and numeric `data-count`; the number of parsed
  rows must exactly equal that declared count.
- Missing attributes, malformed Gem URLs, row/URL identity disagreement, count mismatch,
  unexpected redirects, conflicting duplicate metadata, and unexplained empty inventory fail
  closed.
- Multi-location collapse is allowed only when ID, title, department, and canonical URL agree.
- Detail retrieval validates the Gem host/path, final URL, `og:title`, `og:url`, and a substantial
  `og:description` before attaching the description.
- No API credential, authentication, browser session, CAPTCHA handling, or production browser
  dependency is used.

## Decision

Index Exchange is enabled at high confidence with stable Gem external IDs, complete one-page
inventory accounting, explicit multi-location handling, deferred descriptions, and unknown dates.
S&P Global is enabled at high confidence through the existing strict Workday adapter.
