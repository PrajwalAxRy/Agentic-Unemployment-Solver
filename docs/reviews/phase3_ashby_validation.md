# Phase 3 Ashby adapter validation

## Result

- Status: **passed**
- Generated at: `2026-09-20T17:58:18+05:30`
- Registry version: `0.1.0-provisional`
- Companies: 24
- Outcomes: `{"empty": 1, "success": 23}`
- Observed jobs: 987
- Missing required fields: 0
- Pagination: one complete public `jobs` collection per board; no page tokens
- Official API contract: [Ashby public job-posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)

## Company results

| Rank | Priority | Company | Outcome | Jobs | Pages | Missing | Dates | Exceptions |
|---:|---|---|---|---:|---:|---:|---|---|
| 2 | P1 | Harvey | success | 299 | 1 | 0 | published=299 | none |
| 3 | P1 | Kognitos | success | 7 | 1 | 0 | published=7 | none |
| 5 | P1 | Cartesia | success | 30 | 1 | 0 | published=30 | none |
| 11 | P1 | Deeptune | empty | 0 | 1 | 0 | none | none |
| 34 | P1 | CodeRabbit | success | 47 | 1 | 0 | published=47 | none |
| 35 | P1 | Ema | success | 45 | 1 | 0 | published=45 | none |
| 42 | P1 | Articul8 AI | success | 20 | 1 | 0 | published=20 | none |
| 44 | P1 | Nanonets | success | 11 | 1 | 0 | published=11 | none |
| 48 | P1 | Triomics | success | 18 | 1 | 0 | published=18 | none |
| 50 | P1 | Weave | success | 28 | 1 | 0 | published=28 | none |
| 54 | P1 | Cerebras Systems | success | 113 | 1 | 0 | published=113 | none |
| 55 | P1 | Composio | success | 30 | 1 | 0 | published=30 | none |
| 59 | P1 | Sarvam AI | success | 61 | 1 | 0 | published=61 | none |
| 61 | P1 | WisdomAI | success | 17 | 1 | 0 | published=17 | none |
| 67 | P1 | Atlan | success | 8 | 1 | 0 | published=8 | none |
| 69 | P1 | Kong | success | 72 | 1 | 0 | published=72 | none |
| 80 | P1 | Bolna | success | 9 | 1 | 0 | published=9 | none |
| 93 | P1 | Collinear AI | success | 11 | 1 | 0 | published=11 | none |
| 96 | P1 | Spector.ai | success | 6 | 1 | 0 | published=6 | none |
| 102 | P2 | fal.ai | success | 32 | 1 | 0 | published=32 | none |
| 105 | P2 | d-Matrix | success | 35 | 1 | 0 | published=35 | none |
| 151 | P2 | Handshake | success | 69 | 1 | 0 | published=69 | none |
| 187 | P2 | Smallest.ai | success | 1 | 1 | 0 | published=1 | none |
| 195 | P2 | UptimeAI | success | 18 | 1 | 0 | published=18 | none |

## Corrections and manual evidence

- Cerebras Systems required the exact case-sensitive board name `Cerebras`; the lower-case variant returned truncated invalid JSON during the representative run.
- WisdomAI had moved from the obsolete `Wisdom AI` slug to `Wisdom-AI`; the current public board returned 17 complete jobs.
- Kognitos, Kong, and Cerebras direct job URLs returned public job pages whose titles matched normalized adapter records.
- Deeptune returned the documented healthy empty shape and remains a valid empty board rather than a collection failure.
- Harvey's 299-job, 3.9 MB response passed the five-megabyte bounded client, resolving the earlier two-megabyte discovery-probe limitation.

## Limitations

- Counts are point-in-time observations and will change as employers update boards.
- Ashby board pages are client-rendered; completeness is based on the documented public posting API and the successful full collection, not DOM item counting.
- Sources remain disabled for normal scans until later pipeline phases are complete.
