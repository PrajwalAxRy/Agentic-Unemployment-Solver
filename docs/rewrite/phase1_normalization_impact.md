# Phase 1 — measured impact of adopting shared normalization

`to_change.md` 9.4 warns: *"Expect location-filter output to shift; that is the fix
working, not a regression."* That warning is correct about the **data** but, measured, it
overstates the risk to **decisions**. This file records what actually changes, because
"expected to shift" is exactly the kind of blanket expectation that lets a real regression
through unexamined.

## What the adapters were doing

Measured across `src/job_finder/adapters/` before the change:

| helper | copies | distinct implementations |
|---|---|---|
| `_normalize_text` | 35 | **2** |
| `_normalized_locations` | 30 | **10** |

The two `_normalize_text` variants are behaviourally identical (`\s+` collapse + casefold,
one via a local `_normalize_whitespace`). **Neither strips punctuation** — that is the
entire bug. The shared `normalize_title` does strip it, so the adapter guards were
comparing a punctuation-keeping string against a punctuation-stripped one.

The ten `_normalized_locations` variants genuinely differ: some split on `[,|;/]`, one adds
`\bor\b` case-insensitively, two fall back to `("location unavailable",)`, one returns the
whole string untouched, two do not split at all.

## Title change — this is the fix

| title | adapter-local | shared `normalize_title` |
|---|---|---|
| `Senior ML Engineer, Ads` | `senior ml engineer, ads` | `senior ml engineer ads` |
| `Staff Engineer (AI/ML)` | `staff engineer (ai/ml)` | `staff engineer ai ml` |
| `Data Scientist, Search & Discovery` | `data scientist, search & discovery` | `data scientist search discovery` |
| `Sr. Applied Scientist - Prime Video` | `sr. applied scientist - prime video` | `sr applied scientist prime video` |
| `ML Engineer II` | `ml engineer ii` | `ml engineer ii` (unchanged) |
| `C++ Developer` | `c++ developer` | `c++ developer` (unchanged — `+`/`#` preserved) |

Exactly the 1.2 reproduction table. Note `C++ Developer` survives: `_TITLE_PUNCTUATION` is
`[^\w+#]+`, deliberately keeping `+` and `#` so `C++` and `C#` are not destroyed.

## Location change — shape changes, decisions do not

The shared normalizer does **not** split on commas. It splits on `[;|•]`, newlines and
` / `, then applies city/region aliases:

| location | adapter-local | shared |
|---|---|---|
| `Bengaluru, Karnataka, India` | `('bengaluru', 'karnataka', 'india')` | `('bengaluru karnataka india',)` |
| `Hyderabad, ... \| Pune, ...` | 5 tokens, `india` deduplicated away | `('hyderabad telangana india', 'pune maharashtra india')` |
| `Bangalore or Hyderabad` | `('bangalore or hyderabad',)` | `('bengaluru or hyderabad',)` — alias applied |
| `Gurugram/Noida` | `('gurugram', 'noida')` | `('gurugram noida',)` |

So tuples get **fewer, longer** elements. That looks alarming for
`filters/locations.py` — until you check how matching works. `_contains_phrase` is
`f" {phrase} " in f" {value} "`, i.e. whitespace-delimited substring matching, so
`"india"` still matches inside `"bengaluru karnataka india"`.

**Verified against the real filter, 16 representative locations covering pass / review /
reject, Indian cities, unqualified and qualified remote, and foreign cities:**

```
decision changes: 0/16
```

Every verdict identical. The alias improvement is a genuine gain: `Bangalore or Hyderabad`
now canonicalizes to `bengaluru`, which the local copies never did because they took no
`LocationPolicy`.

## Conclusion

- **Titles: intended behaviour change.** Fixes the identity guards in ten adapters and
  re-keys the job identity hash (see 6.9 — this is why the wipe follows the fix).
- **Locations: representation changes, decisions do not.** Not a silent regression.
- The residual risk is a location string shaped unlike any of the 16 sampled. The
  `_contains_phrase` matching makes a behaviour change unlikely rather than impossible.

Reproduce with `docs/rewrite/check_normalization_impact.py`.
