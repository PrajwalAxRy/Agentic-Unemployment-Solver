# Phase 3 — measured volume after the title-filter swap

`to_change.md` 2.2a asks for this explicitly:

> **Volume impact:** 79% Amazon / 70% Greenhouse vs 11% today. The ~1,500–2,500
> descriptions/scan estimate in 2.2 is **too low** — re-measure after integration.

Measured after integration into `filters/roles.py`, against the same two corpora the
prototype was validated on:

| corpus | titles | survive | rate | prototype (standalone) |
|---|---|---|---|---|
| Amazon India | 1,300 | 940 | **72%** | 79% |
| Greenhouse (14 companies) | 1,120 | 696 | **62%** | 70% |

Integrated rates are ~7-8 points below the standalone prototype, which is expected and
correct: `filter_role` runs the profile-configured `title_exclusions` **before** the
classifier, so titles the prototype passed are now caught earlier by configuration that
was independently reviewed. Configuration still wins.

Against a starting point of 11%, this is roughly a **6x increase** in titles reaching the
description stage.

## What this means for cost

Two effects work in opposite directions and they do not cancel:

**Upward.** Every surviving title is now `CONDITIONAL_DESCRIPTION`. No title grants a pass
any more, so every one of them needs a description fetch and an LLM call. The old pipeline
sent 10 descriptions to the relevance gate in an entire scan; the new one sends everything
that clears location and title.

**Downward.** 2.1 now runs location first, so the 6x multiplier applies only to the
India-eligible subset rather than to every listing fetched. That ordering is what makes
the widening affordable, and it is the real reason 2.1 had to land first.

The 2.2 estimate of ~1,500-2,500 descriptions per full scan remains **unverified from this
side**. These corpora are pre-location samples, so they cannot be converted into a
per-scan description count without a real run. The honest statement is: 6x more titles
survive, applied to a much smaller base than before, and the actual number needs one clean
scan to establish.

Per decision D, if cost bites the first lever is the `description_hash` cache hit rate,
not a model swap. Daily steady state is the delta, not the full scan.

## Reproduce

```
python -c "
import json, sys; sys.path.insert(0, 'src')
from pathlib import Path
from job_finder.core.search_profile import load_search_profile
from job_finder.filters.roles import filter_role
profile = load_search_profile(Path('config/search_profile.toml'))
for name, filename in (('Amazon', 'amazon_india_titles.json'), ('Greenhouse', 'greenhouse_titles.json')):
    titles = [row['title'] for row in json.loads(Path('tests/fixtures/title_corpora', filename).read_text())]
    survived = sum(1 for t in titles if filter_role(t, profile=profile).decision.value != 'reject')
    print(f'{name}: {survived}/{len(titles)} ({100 * survived // len(titles)}%)')
"
```

The corpora themselves now live in `tests/fixtures/title_corpora/` and the three-layer
validation suite runs as `tests/filters/test_title_classifier_corpora.py` on every test
run, rather than only when someone remembers to invoke a script in `prototypes/`.
