# Phase 12 Package C cohort 10 validation

## Scope

This cohort activates Adobe and Oracle / OCI by following their official branded careers sites to
the underlying public enterprise recruiting systems. Adobe uses Workday. Oracle's branded careers
page discloses its current Oracle Candidate Experience host and site number through a public site
settings request.

## Evidence and result

### Adobe

- The official Adobe site links application status to the `external_experienced` Workday board.
- First-attempt live validation returned 557 unique jobs across 28 count-reconciled pages.
- First, middle, and final detail calls returned 10,974, 9,086, and 7,475 normalized description
  characters with matching identities and locations.
- Workday `postedOn` values remain explicit unknown-basis relative-date evidence.

### Oracle / OCI

- The official Oracle / OCI page links into `careers.oracle.com`; browser discovery showed that
  the branded site reads public site settings for host `eeho.fa.us2.oraclecloud.com` and site
  number `CX_45001`.
- Independent direct replay through the existing Oracle Cloud adapter passed on the first attempt:
  2,204 unique jobs across 12 count-reconciled pages.
- First, middle, and final details returned 6,294, 4,227, and 5,987 normalized description
  characters.
- Two short nonterminal pages were surfaced by warning diagnostics while traversal continued by
  explicit offset to the reported total. No repeated page, duplicate identity, or count loss was
  observed.
- Oracle's documented `PostedDate` remains verified publication-date evidence.

## Safety and decision

Both sources use existing strict adapters with bounded requests, page caps, identity checks,
count reconciliation, redirect checks, and deferred details. Browser automation was discovery
only. No browser state, authentication, credential, CAPTCHA handling, access-control bypass, or
production browser dependency is used. Adobe and Oracle / OCI are enabled at high confidence.
