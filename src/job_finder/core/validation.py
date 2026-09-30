"""Shared payload validation for adapters and config loaders.

``to_change.md`` 6.4 counted ``_required_string`` defined 36 times across ``src/`` with
"subtle divergence". Measured precisely: **37 definitions in 17 variants**, across six
different call signatures.

The divergence turned out to be shallower than the audit implied, and that is what makes
this safe to consolidate now rather than never. Every variant has the *same* body -- reject
anything that is not a non-empty string, otherwise return it stripped. What differs is
only the wording of the error message and whether the caller passes a context label:

    "{context} field {key} must be a non-empty string."      (9 files)
    "{path}.{key} must be a non-empty string"                (6 files)
    "{context} {field} must be a non-empty string."          (4 files)
    "Ashby job field {key} must be a non-empty string."      (1 file, per-adapter literal)
    ...

That is why Phase 1 deliberately left it alone: picking one message is a behaviour change,
not an extraction, and it belonged in its own commit where it could be reasoned about.

The chosen contract keeps ``context`` optional. Adapters that pass one get a message that
still names the source ("Ashby job field id must be..."), so diagnostics stay as specific
as they were; adapters that do not get the bare form. Nothing has to change at the call
site except deleting the local copy.
"""

from __future__ import annotations

from collections.abc import Mapping


def required_string(
    raw: Mapping[object, object],
    key: str,
    context: str | None = None,
) -> str:
    """Return ``raw[key]`` as a non-empty stripped string, or raise ``ValueError``.

    ``context`` names the payload for diagnostics, e.g. ``"Ashby job"`` produces
    ``"Ashby job field title must be a non-empty string"``. It is optional because ten of
    the definitions this replaces took no such argument.
    """
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(_message(key, context))
    return value.strip()


def optional_string(
    raw: Mapping[object, object],
    key: str,
    context: str | None = None,
) -> str | None:
    """Return ``raw[key]`` stripped, or ``None`` when absent, null, or blank.

    A present-but-blank value returns ``None`` rather than raising: for an optional field
    "" and "missing" mean the same thing, and the previous local copies agreed on that.
    ``context`` is accepted for signature symmetry with :func:`required_string`, so callers
    can swap between them without rearranging arguments.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(_message(key, context, expectation="a string or null"))
    stripped = value.strip()
    return stripped or None


def clean_optional(value: object) -> str | None:
    """Normalize a value already in hand: stripped string, or ``None``.

    **Not the same function as** :func:`optional_string`, despite 25 adapters having
    called their local copy ``_optional_string``. That one takes a value; this takes a
    mapping and a key. They were never interchangeable, and the shared name is exactly the
    drift 6.4 describes -- two different operations wearing one identifier, which is how a
    "mechanical" consolidation turns into a runtime ``AttributeError``.

    Named for what it does so the two can no longer be confused.
    """
    return value.strip() if isinstance(value, str) and value.strip() else None


def optional_text(value: object, path: str) -> str | None:
    """Validate an optional value in hand: ``None`` stays ``None``, a string is stripped.

    Unlike :func:`clean_optional`, a non-string raises rather than being silently coerced
    to ``None``. The distinction matters where the value came from parsed JSON and a
    number appearing in a string field means the payload is wrong, not that the field is
    absent.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be null or a non-empty string")
    return value.strip()


def required_text(value: object, path: str) -> str:
    """Validate a value that is already in hand rather than looked up in a mapping.

    One definition used this shape (``value``/``path``) instead of mapping lookup. Kept as
    a distinct function rather than folded in, because conflating "this field of this
    payload" with "this value" is how the message formats drifted in the first place.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _message(
    key: str,
    context: str | None,
    *,
    expectation: str = "a non-empty string",
) -> str:
    if context:
        return f"{context} field {key} must be {expectation}"
    return f"{key} must be {expectation}"
