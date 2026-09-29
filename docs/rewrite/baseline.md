# Test baseline — recorded before the to_change.md rewrite

Recorded 2026-09-30, immediately before any Phase 0 change. Every later phase is verified
against these numbers so that regressions introduced by the rewrite are distinguishable
from failures that were already present.

## Result

```
617 tests collected
613 passed, 4 failed   (13.3s)
```

## The 4 failures are environmental, not real

All four live in `tests/test_smoke.py` and assert on **Windows-style backslash paths**.
They fail on Linux and would pass on the developer's Windows machine:

| Test | Asserts | Got on Linux |
|---|---|---|
| `test_cli_accepts_full_registry_recency_measurement` | `config\search_profile.toml` | `config/search_profile.toml` |
| `test_cli_state_reset_requires_backup_and_confirmation` | `state\jobs.sqlite3` | `state/jobs.sqlite3` |
| `test_cli_accepts_two_pass_persistence_verification` | `state\phase7_validation.sqlite3` | `state/phase7_validation.sqlite3` |
| `test_cli_accepts_guarded_seniority_validation` | `reports\prior.json` (same class) | forward-slash form |

These assert `str(Path(...)) == "literal\\with\\backslashes"`, which is platform-dependent
by construction. **Not fixed as part of the rewrite** — out of scope, and changing them
would alter the baseline being measured against. Worth fixing separately with
`Path(...) == Path(...)` comparison or `os.sep`.

**Acceptance rule for every later phase: 613 passing, and the only failures permitted are
these same 4.** Any new failure is a real regression and must be resolved before the phase
is considered done.

## Toolchain note (Linux dev VM only)

The project requires Python 3.12 (`StrEnum`, `datetime.UTC`, PEP 695 generics). The
checked-in `.venv/` is a **Windows** virtualenv (`Scripts/`, `.exe`) and is unusable on
Linux — it must not be modified. A separate Linux venv is used instead:

```
UV_NATIVE_TLS=1 uv python install 3.12
UV_NATIVE_TLS=1 uv venv --python 3.12 <venv>
UV_NATIVE_TLS=1 UV_LINK_MODE=copy uv pip install --python <venv>/bin/python pytest openai
UV_NATIVE_TLS=1 UV_LINK_MODE=copy uv pip install --python <venv>/bin/python --no-deps -e .
```

Two gotchas cost real time and are worth recording:

- **`UV_NATIVE_TLS=1` is required.** Without it, uv's Python download fails with
  `invalid peer certificate: UnknownIssuer` behind the TLS-intercepting proxy. PyPI works
  regardless; only the GitHub-hosted python-build-standalone download is affected.
- **Build the venv on local disk, not on the mounted project folder.** The mount is a slow
  network filesystem — a single package install took 37s there versus under a second
  locally, and an interrupted install left a half-written `pygments` that broke pytest.
