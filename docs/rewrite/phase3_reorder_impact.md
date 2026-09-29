# Phase 3 — what reordering location before title actually does

`to_change.md` 2.1 justifies the reorder like this:

> Location is far more selective and unambiguous. Running it first keeps ~19 Bank of
> America US/10+yr rows out of the review queue entirely (~25% of the current 128).

The reorder is worth doing, but **that specific justification does not survive contact
with the scan data**, and the difference matters for what to expect afterwards.

## What the 19 Bank of America rows actually are

From `reports/latest_scan.json` (the real 2026-09-29 run):

```
Bank of America review rows: 19
categories: {'detail_location_unavailable': 19}
sample locations: '2 Locations', '3 Locations', '2 Locations', '5 Locations', ...
```

All nineteen are `detail_location_unavailable`, not US-geography rejections. These are
Workday listings whose list payload says `"2 Locations"` instead of naming them, so the
adapter must fetch the detail page to discover the real geography. In the 2026-09-29 run
that fetch failed, so the rows landed in review with no location decision at all.

Reordering does not remove them. They still require the same detail fetch, still fail the
same way, and still land in review. What fixes these is **Phase 0**, which made the
underlying fetch failure visible and diagnosable, not 2.1.

The arithmetic is also off: 19 of 128 is **15%**, not ~25%.

## What the reorder does do

Verified against the existing filter tests:

| | before | after |
|---|---|---|
| `role_counts` | unchanged | unchanged |
| `location_counts` | `{pass: 2, review: 1}` | `{pass: 3, review: 1}` |
| `final_counts` | `{rejected: 1, retained: 2, review: 1}` | **identical** |

Every final decision is the same. The extra `pass` is a row (`Product Manager, AI`) whose
location was previously never evaluated because the title filter rejected it first.

So the measurable effects are:

1. **Every recency-eligible row now gets a location decision**, which makes
   `location_counts` a true denominator rather than "rows that happened to survive the
   title stage". That is a reporting improvement available immediately.
2. **Deterministic geography rejection short-circuits before any title work**, including
   before the Workday location detail fetch. No network request is issued for a job in an
   ineligible country.
3. **It is a precondition for 2.2a.** This is the real reason to do it now. The new title
   filter raises the pass rate from 11% to 70-79%, so the title stage stops being
   selective. Putting the selective filter first is what keeps the description-fetch
   volume survivable once that lands.

Point 3 is the actual argument for 2.1, and it holds regardless of the Bank of America
claim being wrong.

## What to expect

Do **not** expect the review queue to shrink by 19 rows after this change. Those rows are
a detail-fetch failure, and they should resolve on the first clean re-run now that Phase 0
surfaces why the fetch failed. If they persist, the cause is in the Workday detail path,
not in filter ordering.
