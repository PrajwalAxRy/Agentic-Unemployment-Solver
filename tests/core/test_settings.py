"""Tests for the minimal application settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_finder.core.settings import ApplicationSettings, load_application_settings


def test_sample_configuration_loads() -> None:
    settings = load_application_settings(Path("config/settings.example.toml"))

    assert settings == ApplicationSettings(
        schema_version=1,
        reports_directory=Path("reports"),
        state_directory=Path("state"),
    )


def test_unknown_settings_schema_is_rejected(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        'schema_version = 2\n[application]\nreports_directory = "reports"\n'
        'state_directory = "state"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported settings schema_version"):
        load_application_settings(settings_path)
