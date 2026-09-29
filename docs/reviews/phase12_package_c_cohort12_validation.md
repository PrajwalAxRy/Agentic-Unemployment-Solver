# Phase 12 Package C cohort 12 validation

## Decision

Confluent is activated through its current public Ashby board. The old saved Confluent careers
detail was stale and rate-limited; current public job evidence identifies the branded
`jobs.ashbyhq.com/Confluent` board and its standard public posting API.

The registry-backed first-attempt gate returned 18 complete jobs on one page, with no missing
required fields or diagnostics. One listing is India-located. First, middle, and final samples
contained 4,474, 5,085, and 6,922 normalized description characters. All sampled canonical URLs
remained on `jobs.ashbyhq.com`.

The existing Ashby adapter supplies stable external IDs, full listing-payload descriptions, and
verified `publishedAt` timestamps. Confluent is enabled at high confidence; no browser state,
credential, authentication, or access-control bypass is used in production.

## P1 residual review

The other disabled P1 companies were rechecked against the accumulated browser, public-search,
and direct-request evidence. None met the activation gate:

- Microsoft has a deterministic adapter, but the public host's rolling quota still prevents a
  clean repeatable full-source gate.
- Rippling's branded page renders current roles, but raw HTML does not contain the inventory and
  its client-side Algolia access parameters are not suitable for committed production
  configuration.
- Kore.ai and Yellow.ai expose visible careers content without a consistent independently
  replayable complete inventory; Yellow.ai's advertised Zoho feed reports zero despite a visible
  role link.
- LinkedIn exposes a partial sign-in-overlaid feed; Roku requires an AWS WAF challenge for full
  descriptions; Flipkart exposes neither functional detail links nor a public structured
  inventory.
- Zerodha and Maxim AI show defensible empty states but no deterministic completeness contract.
- Mayhem Studios publishes seven Bangalore role summaries, but applications and details lead only
  to LinkedIn. Mrsool likewise directs applicants to LinkedIn rather than an official complete
  inventory.
- Meta, Zenskar, Zomato / Blinkit, and X still lack identity-safe, complete public listing and
  detail contracts. NVIDIA remains explicitly unsupported under the approved no-bypass decision.

All remain accounted for and disabled rather than being silently omitted or partially collected.
