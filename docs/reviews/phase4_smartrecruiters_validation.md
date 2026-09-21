# Phase 4 SmartRecruiters validation

## Result

The public SmartRecruiters postings API passed full adapter-group validation on 2026-09-21.
Requests used the bounded shared HTTP client without authentication, cookies, or browser-session
collection. Offset pagination was checked against `totalFound`; public per-job detail endpoints
were confirmed for description retrieval.

| Company | Jobs | Pages | Missing required fields | Date evidence |
|---|---:|---:|---:|---|
| Entropik | 3 | 1 | 0 | 3 `releasedDate` published |
| Bosch Global Software Technologies | 4,806 | 49 | 0 | 4,806 `releasedDate` published |
| Freshworks | 136 | 2 | 0 | 136 `releasedDate` published |

The complete sanitized runtime report is `reports/smartrecruiters_full_verification.json`; it is
ignored by Git. Fixture coverage includes healthy count-checked pagination, empty and malformed
responses, access restrictions, partial failures, duplicate identifiers, stable direct URLs,
published-date mapping, and detail-description retrieval.
