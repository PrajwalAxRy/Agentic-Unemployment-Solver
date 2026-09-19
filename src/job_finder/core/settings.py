"""Minimal Phase 0 application settings loader."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    """Filesystem settings needed before product configuration is introduced."""

    schema_version: int
    reports_directory: Path
    state_directory: Path


def load_application_settings(path: Path) -> ApplicationSettings:
    """Load the non-secret application settings file."""
    with path.open("rb") as stream:
        raw: dict[str, Any] = tomllib.load(stream)

    schema_version = raw.get("schema_version")
    application = raw.get("application")
    if schema_version != 1:
        msg = f"unsupported settings schema_version: {schema_version!r}"
        raise ValueError(msg)
    if not isinstance(application, dict):
        msg = "settings must contain an [application] table"
        raise ValueError(msg)

    reports_directory = application.get("reports_directory")
    state_directory = application.get("state_directory")
    if not isinstance(reports_directory, str) or not reports_directory.strip():
        msg = "application.reports_directory must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(state_directory, str) or not state_directory.strip():
        msg = "application.state_directory must be a non-empty string"
        raise ValueError(msg)

    return ApplicationSettings(
        schema_version=schema_version,
        reports_directory=Path(reports_directory),
        state_directory=Path(state_directory),
    )
