"""Tests for versioned seniority prompt loading and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_finder.matching.prompt import load_seniority_prompt

ROOT = Path(__file__).resolve().parents[2]


def test_approved_prompt_loads_and_renders_all_inputs() -> None:
    prompt = load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml")

    rendered = prompt.render(
        title="Machine Learning Engineer",
        description="Candidates need 3+ years of experience.",
        target_description="Open to candidates with fewer than five years.",
    )

    assert prompt.prompt_version == "1.0.0"
    assert "3+ years of experience" in rendered
    assert "Machine Learning Engineer" in rendered
    assert "fewer than five years" in rendered
    assert "Evidence must be a short verbatim excerpt" in prompt.system_prompt


def test_prompt_rejects_blank_render_fields() -> None:
    prompt = load_seniority_prompt(ROOT / "config" / "seniority_prompt.toml")

    with pytest.raises(ValueError, match="description must be a non-empty string"):
        prompt.render(title="ML Engineer", description=" ", target_description="Under five")
