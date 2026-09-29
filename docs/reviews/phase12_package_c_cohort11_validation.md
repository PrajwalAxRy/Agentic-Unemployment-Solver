# Phase 12 Package C cohort 11 validation

## Scope and evidence

This cohort activates American Express through the public Oracle Candidate Experience board linked
by its official branded careers site. Browser discovery observed the public site-settings request
for host `egug.fa.us2.oraclecloud.com` and site number `CX_1`; production uses the existing bounded
Oracle Cloud adapter directly.

The first-attempt live gate returned 507 unique jobs across three count-reconciled pages with no
diagnostic. First, middle, and final detail calls returned matching identities and 3,415, 3,410,
and 3,306 normalized description characters. Oracle's documented `PostedDate` is retained as
verified publication-date evidence.

## Safety and decision

The source inherits strict page caps, total reconciliation, repeated-page and duplicate detection,
canonical URL and detail-identity checks, and bounded retries. Browser automation was discovery
only. No browser state, authentication, credential, CAPTCHA handling, access-control bypass, or
production browser dependency is used. American Express is enabled at high confidence.
