"""Phase-gate validation and reporting tools.

Relocated out of ``src/job_finder/`` per ``to_change.md`` 6.7 (decision B). These modules
are one-time or long-running validation artifacts -- a ~100-minute two-pass idempotency
check, a full-registry network recency sweep, and the H9 seniority quality report
generator. None of them run during a daily scan, and keeping them in the package anchored
``filter_verification``'s API so it could not be refactored freely.

They remain fully runnable and tested; this is a relocation, not a deletion.
"""
