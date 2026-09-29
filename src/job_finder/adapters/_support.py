"""Shared adapter helpers.

Every adapter carried its own copy of the same utility tail -- 201 definitions of nine
helpers across 36 files, ~1,800 LOC, for functions whose bodies were in most cases
byte-identical (``to_change.md`` 6.4). Naming had already drifted (greenhouse and ashby
call it ``_failed_result``, lever splits it into ``_result`` plus ``_diagnostic``), and
that drift is the early warning: copies do not stay identical, and when they diverge
silently the difference shows up as inconsistent behaviour between companies rather than
as a bug anyone can see. That is exactly what happened to the normalization helpers (6.3).

This module holds the helpers whose duplicates were genuinely interchangeable. Scope is
deliberately conservative per decision C: extract the shared bodies, leave each adapter's
control flow alone. The full ``list_jobs`` template-method rewrite is deferred until the
adapter shape has stabilised across a wider sample.

Two helpers are **not** here on purpose:

``_required_string`` / ``_optional_string``
    14 and 4 genuinely different variants. Some take a ``path`` argument, some raise
    ``GatewayProviderError`` instead of ``ValueError``, and the error strings are part of
    adapter-specific diagnostics. Consolidating them means choosing one error contract for
    all 28 call sites, which is a behaviour change, not an extraction. Left for the
    ``core/validation.py`` work.
"""

from __future__ import annotations

from collections.abc import Iterable

from job_finder.adapters.http_client import HttpFailureCategory, HttpRequestError
from job_finder.core.job_contracts import NormalizedJob
from job_finder.core.source_contracts import (
    SUPPORTED_ADAPTER_RESULT_SCHEMA_VERSION,
    AdapterDiagnostic,
    AdapterOutcome,
    AdapterResult,
    CompanySource,
    DiagnosticSeverity,
)


def diagnostic(
    category: str,
    severity: DiagnosticSeverity,
    message: str,
    **context: object,
) -> AdapterDiagnostic:
    """Build a diagnostic with stringified context values.

    Replaces 34 local ``_diagnostic`` definitions. The four "variants" differed only in the
    annotation of ``**context`` (``object`` vs ``int | str``); the bodies were identical.
    ``object`` is the correct and most permissive of those.
    """
    return AdapterDiagnostic(
        category=category,
        severity=severity,
        message=message,
        context={key: str(value) for key, value in context.items()},
    )


def request_outcome(error: HttpRequestError) -> AdapterOutcome:
    """Map a transport failure to an adapter outcome.

    Replaces 30 identical local definitions -- a single variant across every file that
    defined it, so this extraction cannot change behaviour.
    """
    return (
        AdapterOutcome.BLOCKED
        if error.category is HttpFailureCategory.ACCESS_BLOCK
        else AdapterOutcome.FAILED
    )


def unique_strings(values: Iterable[str | None]) -> list[str]:
    """Strip, drop empties, and deduplicate case-insensitively, preserving order.

    Replaces 18 local definitions across two variants. The variants differed only in
    whether ``None`` was tolerated (``pageup_xml_feed`` accepted it, the rest did not);
    accepting it is a superset, so every existing caller keeps working.
    """
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
        value = raw.strip()
        key = value.casefold()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def adapter_result(
    source: CompanySource,
    outcome: AdapterOutcome,
    jobs: Iterable[NormalizedJob],
    page_count: int,
    diagnostics: Iterable[AdapterDiagnostic] = (),
    *,
    complete: bool = True,
) -> AdapterResult:
    """Assemble an ``AdapterResult``.

    Replaces the common ``_result`` / ``_failed_result`` bodies. ``AdapterResult``'s own
    ``__post_init__`` enforces the real invariants, so this is assembly only -- it
    deliberately adds no validation of its own.
    """
    return AdapterResult(
        schema_version=SUPPORTED_ADAPTER_RESULT_SCHEMA_VERSION,
        source=source,
        outcome=outcome,
        jobs=tuple(jobs),
        complete=complete,
        page_count=page_count,
        diagnostics=tuple(diagnostics),
    )


def failed_result(
    source: CompanySource,
    category: str,
    message: str,
    *,
    outcome: AdapterOutcome = AdapterOutcome.FAILED,
    page_count: int = 1,
    **context: object,
) -> AdapterResult:
    """Build a failed result carrying one diagnostic.

    The single most repeated shape in the adapter layer: something went wrong, record why,
    return no jobs, and mark the run incomplete so downstream cannot mistake the empty
    result for an exhausted board. That last part matters for the staleness logic in
    Phase 4 -- an incomplete run must never feed the absence counter.
    """
    return AdapterResult(
        schema_version=SUPPORTED_ADAPTER_RESULT_SCHEMA_VERSION,
        source=source,
        outcome=outcome,
        jobs=(),
        complete=False,
        page_count=page_count,
        diagnostics=(diagnostic(category, DiagnosticSeverity.ERROR, message, **context),),
    )
