"""Guard: normalization has exactly one implementation (to_change.md 6.3, 9.4).

Before Phase 1 there were **35** local copies of ``_normalize_text`` and **30** of
``_normalized_locations`` across ``src/job_finder/adapters/``, and **zero** adapters
imported the shared ``job_finder.normalization`` module that already existed. The location
helper had drifted into ten genuinely different implementations, so the same location
string produced different tuples depending only on which company the job came from.

The title half of that divergence is what broke the identity guards in ten adapters and
stranded 78/78 Google rows: the local copies kept punctuation, the shared normalizer
stripped it, and the two were compared against each other.

9.4 asks for a lint guard "or the copies grow back". This is it. It is a test rather than
a ruff rule because ruff has no cross-file "this name must not be defined here" check, and
a test failure names the offending file directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ADAPTERS = Path(__file__).parents[1] / "src" / "job_finder" / "adapters"

# Defining any of these inside an adapter reintroduces the divergence. Use the shared
# functions in job_finder.normalization.jobs instead:
#   _normalize_text       -> normalize_text / normalize_title (pick by intent)
#   _normalized_locations -> normalize_source_locations
_BANNED_HELPER_NAMES = frozenset({"_normalize_text", "_normalized_locations"})


def _adapter_modules() -> list[Path]:
    return sorted(path for path in _ADAPTERS.glob("*.py") if path.name != "__init__.py")


@pytest.mark.parametrize("path", _adapter_modules(), ids=lambda path: path.name)
def test_adapter_does_not_redefine_shared_normalization(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    redefined = sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in _BANNED_HELPER_NAMES
    )
    assert not redefined, (
        f"{path.name} redefines {redefined}. Import from job_finder.normalization.jobs "
        "instead: normalize_text/normalize_title for text, normalize_source_locations for "
        "locations. Local copies are how the same string came to normalize differently per "
        "company (to_change.md 6.3)."
    )


def test_every_adapter_that_normalizes_uses_the_shared_module() -> None:
    """An adapter that normalizes anything must source it from the shared module."""
    offenders = []
    for path in _adapter_modules():
        source = path.read_text(encoding="utf-8")
        normalizes = "normalize_title(" in source or "_shared_locations(" in source
        imports_shared = "from job_finder.normalization.jobs import" in source
        if normalizes and not imports_shared:
            offenders.append(path.name)
    assert not offenders, f"adapters normalize without importing the shared module: {offenders}"


def test_shared_module_is_actually_imported_by_adapters() -> None:
    """The regression that started it all: the shared module existed and nothing used it.

    ``grep -rln "from job_finder.normalization" src/job_finder/adapters/`` returned 0 files
    while 65 local copies sat alongside it. If this count ever returns to zero the
    refactor has been undone.
    """
    importers = [
        path.name
        for path in _adapter_modules()
        if "from job_finder.normalization" in path.read_text(encoding="utf-8")
    ]
    assert len(importers) >= 30, (
        f"only {len(importers)} adapters import shared normalization; "
        "expected the large majority of them to"
    )
