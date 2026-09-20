# Adapter fixtures

Fixtures preserve the public source's response shape while keeping examples small, deterministic,
and free of credentials, cookies, or full production payloads.

## Ashby

- `ashby/healthy.json`: two representative listings, including secondary locations and the
  listing-payload description fields.
- `ashby/empty.json`: the observed healthy empty-board shape.
- `ashby/malformed.json`: a jobs collection with missing required fields.
- `ashby/access_block.html`: a sanitized challenge-page response used to prove content-type and
  access failures cannot be mistaken for valid job data.

Ashby's public posting endpoint returns one complete `jobs` collection without page tokens. The
adapter therefore reports one page and validates the entire collection; paginated fixture behavior
is not applicable to this adapter family.

## Greenhouse

- `greenhouse/healthy.json`: two representative jobs with full content, including one reliable
  `first_published` value and one update-date fallback.
- `greenhouse/empty.json`: a complete zero-job response whose `meta.total` agrees with `jobs`.
- `greenhouse/malformed.json`: a listing missing required job fields.
- `greenhouse/incomplete.json`: a deliberately inconsistent `meta.total` used to reject incomplete
  collection results.

Greenhouse's public list endpoint returns one `jobs` collection and a `meta.total` completeness
check. The adapter requests `content=true` so descriptions are available without per-job requests.
