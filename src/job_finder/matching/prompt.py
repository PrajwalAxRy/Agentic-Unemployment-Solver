"""Versioned seniority prompt configuration and rendering."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SeniorityPrompt:
    """Validated prompt text and stable version."""

    schema_version: int
    prompt_version: str
    system_prompt: str
    user_prompt_template: str

    def render(self, *, title: str, description: str, target_description: str) -> str:
        """Render only the approved job fields and target definition."""
        return self.user_prompt_template.format(
            title=_required_text(title, "title"),
            description=_required_text(description, "description"),
            target_description=_required_text(target_description, "target_description"),
        )


def load_seniority_prompt(path: Path) -> SeniorityPrompt:
    """Load and validate the versioned TOML prompt."""
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"unsupported seniority prompt schema_version: {schema_version!r}")
    prompt = SeniorityPrompt(
        schema_version=schema_version,
        prompt_version=_required_text(raw.get("prompt_version"), "prompt_version"),
        system_prompt=_required_text(raw.get("system_prompt"), "system_prompt"),
        user_prompt_template=_required_text(
            raw.get("user_prompt_template"),
            "user_prompt_template",
        ),
    )
    for placeholder in ("{title}", "{description}", "{target_description}"):
        if placeholder not in prompt.user_prompt_template:
            raise ValueError(f"user_prompt_template must contain {placeholder}")
    return prompt


def _required_text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()
