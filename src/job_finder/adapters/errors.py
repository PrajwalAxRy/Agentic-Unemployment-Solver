"""Detail-fetch exception taxonomy.

``get_job_detail`` historically raised bare ``ValueError`` for every kind of failure, using
it as both its assertion vocabulary and its parse-error vocabulary. ``google_careers.py``
alone raises it from six distinct checks -- source mismatch, URL identity mismatch,
response-URL mismatch, title mismatch, missing India location, and empty required section.
All six collapsed into one indistinguishable string at the catch site, so a 403 and "Google
changed a heading" looked identical. That is how a trivial punctuation bug in title
normalization survived across ten adapters and 97 rows while presenting as a network
failure (``to_change.md`` 1.1, 9.3).

The split that matters operationally is **identity mismatch** versus **missing content**:

``DetailIdentityMismatch``
    The fetched page is not the job that was asked for, or cannot be proven to be. Usually
    means a listing/detail correlation assumption broke -- a normalization change, a URL
    scheme change, or a redirect. Investigate the adapter, not the network.

``DetailContentMissing``
    The right page was fetched but a required field or section is absent. Usually means the
    site's markup changed, or the posting genuinely lacks the field.

``DetailPostingClosed``
    The right page was fetched and the board itself says the posting is closed (for example
    SuccessFactors' "Sorry, this position has been filled."), usually while the listing still
    advertises it. Not an adapter fault and not worth a retry: the job is dropped from the
    scan rather than judged from its title.

All three derive from ``DetailUnavailable``, which derives from ``ValueError`` so that existing
``except ValueError`` handlers keep working unchanged during migration. This follows the
codebase's own precedent -- ``AdapterConfigurationError``, ``SeniorityResponseError`` and
``_RemoteApiError`` all subclass builtins the same way.
"""

from __future__ import annotations


class DetailUnavailable(ValueError):
    """A job detail could not be produced.

    Base of the detail-fetch taxonomy. Subclasses ``ValueError`` deliberately: call sites
    that predate this module still catch ``ValueError`` and must keep working.
    """


class DetailIdentityMismatch(DetailUnavailable):
    """The fetched detail page could not be confirmed as the requested job.

    Raised when a listing-to-detail correlation check fails: mismatched source, job URL,
    response URL, or title. Nearly always an adapter-side assumption that has broken rather
    than a transport problem -- treat a burst of these as a broken adapter, not a flaky site.
    """


class DetailContentMissing(DetailUnavailable):
    """The detail page was the right job but a required field or section was empty.

    Distinct from :class:`DetailIdentityMismatch` because the remedy differs: the page was
    correctly identified, so this points at changed markup or a genuinely incomplete posting.
    """


class DetailPostingClosed(DetailUnavailable):
    """The board's detail page states the posting is closed, filled or withdrawn."""


#: ``failure_category`` reported by ``_ensure_description`` for :class:`DetailPostingClosed`.
POSTING_CLOSED = "posting_closed"


def exception_category(error: BaseException) -> str:
    """Return a short stable category for reporting.

    Used to fill the ``reason_code`` / ``exception_category`` slots that the report schema
    already carries, so that failures aggregate into named causes instead of a single
    opaque ``description_unavailable`` bucket.
    """
    return type(error).__name__
