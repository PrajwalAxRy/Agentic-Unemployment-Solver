# Recency and publication-date coverage contract

**Schema version:** 1

**First-release window:** rolling 10 days

**Current uncertainty mode:** `hybrid`

**Final uncertain-date treatment:** H5 option 4, approved 2026-09-22

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

Verified `published` evidence enters the strict inside/outside age decision. `updated` and
unverified `unknown` values remain in the uncertain-date section. A persisted `first_seen`
timestamp may age an uncertain listing forward from its first observation, but never establishes
its publication time.

## Approved hybrid behavior

- Reliable publication dates receive a strict inside- or outside-window decision.
- Updated values, unverified values, missing values, and date-only boundary overlaps stay visible
  in the separate uncertain-date section.
- Jobvite and SuccessFactors may retrieve their verified detail dates only after deterministic
  title and India-location filters.
- Workday, Lever, Darwinbox, and Eightfold retain their source values as uncertain and use a
  persisted `first_seen_at` only for forward-only aging after the initial baseline.
- Raw date text, normalized date basis, job URL, and `first_seen_at` remain retained.
- An updated date is never relabelled as an original publication date.

| Evidence family | Approved treatment |
|---|---|
| Verified publication timestamp | Strict ten-day decision. |
| Greenhouse `updated_at` fallback and Oracle date-only boundary overlap | Separate uncertain-date section. |
| Jobvite and SuccessFactors list-date omission | Fetch verified public detail date after deterministic pre-detail filters. |
| Workday `postedOn`, Lever `createdAt`, Darwinbox `job_posting_on`, Eightfold `t_create` | Separate uncertain-date section; age forward only from persisted `first_seen`. |

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

## H5 decision record

The report presented the following options and the user approved option 4 on 2026-09-22:

1. Exclude uncertain-date jobs from strict ten-day results.
2. Include them in a clearly separate uncertain-date section.
3. Use `first_seen` for forward-only recency after the initial baseline.
4. Apply a documented hybrid policy by adapter or evidence type.

The approved choice is represented in search-profile version `1.1.0`, the adapter-specific table
above, fixtures, and boundary tests. A full-registry rerun under that profile remains the final
Phase 5 validation gate.
