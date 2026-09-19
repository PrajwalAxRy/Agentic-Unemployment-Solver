# Local development

## Supported environment

- CPython 3.12.x
- `uv` 0.8 or newer
- Git

The project intentionally supports Python 3.12 for the first release. `.python-version` records the
selection, `pyproject.toml` rejects other minor versions, and `uv.lock` pins the complete resolved
development environment.

## Set up a clean checkout

From the repository root:

```powershell
uv sync --all-groups --locked --python 3.12
```

This creates an ignored `.venv` and installs the editable application plus the locked validation
tools. No provider credential is required during Phase 0.

## Run validation

Use the same command before every commit:

```powershell
uv run --locked python scripts/validate.py
```

The command runs, in order:

1. Ruff formatting checks.
2. Ruff lint checks.
3. Strict mypy checks for application and validation code.
4. Pytest with strict configuration and marker handling.

The command exits at the first failed layer and returns a nonzero status.

## Smoke commands

```powershell
uv run --locked job-finder --version
uv run --locked python -m job_finder --version
```

## Configuration and secrets

`config/settings.example.toml` is the tracked non-secret Phase 0 configuration. `.env.example`
contains only non-secret placeholders. Do not commit `.env` or any variant containing credentials.
Provider variables will be added only after the mocked LLM integration passes in Phase 8.

## Generated files

The following locations are intentionally local:

- `reports/` for generated human- and machine-readable reports.
- `state/` for the local job-history database and backups.
- `diagnostics/`, `browser-captures/`, `http-cache/`, and `llm-output/` for temporary evidence.
- `outputs/` for pre-existing provenance output, including the immutable source workbook.

Only the placeholder files in `reports/` and `state/` are tracked. Never use a generated database
or live report as a fixture; create sanitized fixture data under `tests/fixtures/` instead.
