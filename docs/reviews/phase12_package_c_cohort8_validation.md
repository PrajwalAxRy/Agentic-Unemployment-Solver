# Phase 12 Package C cohort 8 validation

## Scope

This cohort activates Eightfold AI through its public PCSx careers surface. The branded careers
page identifies the required shared-host `domain` value and calls public JSON listing and detail
endpoints. The implementation is a reusable custom adapter rather than an Eightfold-platform
assumption: it accepts only a strictly configured HTTPS host and domain pair and validates every
returned identity and URL.

## Evidence and result

- Official page: `https://app.eightfold.ai/careers?domain=volkscience.com&hl=en`
- Public listing endpoint: `/api/pcsx/search`
- Public detail endpoint: `/api/pcsx/position_details`
- Live activation retry: `reports/phase12_eightfold_ai_activation_retry.json`
- Result: `success`, 59 unique jobs, six pages, complete count agreement, first-attempt success.
- Three representative detail calls returned matching identity, title, location, canonical URL,
  timestamps, and substantial descriptions (4,858, 7,085, and 5,307 normalized characters).
- One listing has no location in the public payload. It is retained as `Location unavailable`,
  marked in source metadata, and reported by a warning diagnostic rather than silently dropped.
- PCSx `creationTs`, `postedTs`, and `externallyPostedTs` are retained as unknown-basis evidence.
  Detail retrieval requires the two posted timestamps to agree but does not promote them to a
  verified publication date.

## Safety and completeness controls

- Pagination stops only when the number of unique jobs equals the endpoint's stable reported
  count. Empty early pages, count drift, duplicates, over-collection, schema changes, redirects,
  and a 100-page safety cap fail closed.
- Source configuration rejects alternate paths, ports, credentials, fragments, query shapes,
  adapter keys, and malformed DNS names.
- Listing and detail identity, title, locations, position path, and public URL must agree.
- Requests use the shared bounded HTTP client; no browser automation, authentication, CAPTCHA,
  access-control bypass, or production browser dependency is introduced.

## Decision

Eightfold AI is enabled at high confidence with `external_id` identity and deferred detail
retrieval. The generated live report remains ignored local evidence and is not committed.
