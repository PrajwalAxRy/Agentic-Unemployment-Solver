# Recency and publication-date coverage contract

**Schema version:** 1

**First-release window:** rolling 10 days

**Current uncertainty mode:** `measure_then_decide`

**Final uncertain-date treatment:** deliberately unresolved until checkpoint H5

## Rolling-window calculation

The scan time is an explicit timezone-aware instant. For a verified first-publication timestamp,
the inclusive boundary is:

```text
boundary = scan_at - 10 days
```

- A timestamp exactly on the boundary is inside the window.
- A timestamp one second after the boundary is inside the window.
- A timestamp one second before the boundary is outside the window.
- Timezone offsets are compared as instants, not as displayed wall-clock values.
- A future publication timestamp is invalid and never silently passes.
- A date-only value retains date precision. If that date overlaps the exact timestamp boundary, the
  result is uncertain instead of inventing a publication time.

## Date evidence states

Every observed listing belongs to exactly one evidence state:

| State | Meaning |
|---|---|
| `reliable` | A source field has been verified as first-publication evidence and contains a usable value. |
| `uncertain` | A value exists but represents an update, unverified publication field, `first_seen`, ambiguous date-only boundary, or another non-final basis. |
| `invalid` | A date value is impossible or unusable, such as a future timestamp. |
| `missing` | The source exposes no usable date value. |

Only verified `published` evidence can currently enter the inside/outside age decision. `updated`,
`first_seen`, and `unknown` bases remain uncertain while the profile uses `measure_then_decide`.

## Measure-then-decide behavior

Until checkpoint H5:

- Reliable publication dates receive an inside- or outside-window decision.
- Uncertain, invalid, and missing dates enter a separate measurement pool.
- Measurement-pool jobs are not classified as inside or outside the ten-day window.
- Raw date text, normalized date basis, job URL, and `first_seen_at` availability are retained.
- An updated date is never relabelled as an original publication date.

The runtime rejects any attempt to activate a final uncertain-date behavior before H5 records the
user's decision.

## Required Phase 5 company metrics

Every enabled company must appear exactly once in one of these categories:

| Category | Definition |
|---|---|
| `all_reliable` | Every observed listing has reliable first-publication evidence. |
| `mixed` | At least one listing is reliable and at least one is uncertain, invalid, or missing. |
| `no_reliable` | Listings were observed, but none has reliable first-publication evidence. |
| `no_listings` | The source was assessed successfully and returned no listings. |
| `unassessed` | Source access or another failure prevented a date assessment. |

The report records counts and percentages for all five categories. `no_listings` and `unassessed`
remain separate from date failures.

## Required Phase 5 listing metrics

Across all observed listings, the report records:

- Reliable, uncertain, invalid, and missing counts.
- The percentage of observed listings in each state.
- The same counts for each adapter or source family.
- The count with a timezone-aware `first_seen_at` value.

The report also retains representative company names, job URLs, raw date labels, normalized bases,
and interpretations for each uncertainty pattern so the H5 decision is evidence-based.

## `first_seen` interpretation

An available `first_seen_at` proves when this system first observed a listing; it does not prove when
the employer first published it. The Phase 5 report must distinguish:

1. Availability: whether the runtime captured `first_seen_at` for an observation.
2. Forward usefulness: whether later scans can use that value consistently after an initial
   baseline.
3. Historical limitation: first seen cannot establish the age of a listing already present during
   the initial scan.

## Mandatory H5 decision

After full-registry listing and date normalization, the report must recommend but not select one of:

1. Exclude uncertain-date jobs from strict ten-day results.
2. Include them in a clearly separate uncertain-date section.
3. Use `first_seen` for forward-only recency after the initial baseline.
4. Apply a documented hybrid policy by adapter or evidence type.

The approved choice must then be represented in the search profile, adapter date strategies,
fixtures, and boundary tests before Phase 6 begins.
