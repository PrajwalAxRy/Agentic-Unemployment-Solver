"""The model is configuration, never code (execution decision 3).

`to_change.md` decision D records "stay on the currently configured model". That is a
configuration decision, and the way it goes wrong is someone writing the model name into
source as a default -- at which point a stale or wrong name becomes a silent runtime
failure, and the config path stops being exercised.

These tests keep the model name out of `src/` and keep the configured-vs-returned ID
visible in the log.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from job_finder.matching.evaluator import UsageLimits
from job_finder.matching.openai_client import (
    AmdGatewaySettings,
    GatewayProviderError,
    check_gateway_connectivity,
    configuration_presence,
    load_gateway_settings,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "job_finder"

# Model-family names that must never appear as string literals in source.
_MODEL_NAME_PATTERN = re.compile(
    r"\b(gpt-[0-9]|claude-[0-9]|gemini-[0-9]|llama-?[0-9]|mistral-|luna\b)",
    re.IGNORECASE,
)


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


@pytest.mark.parametrize(
    "path",
    sorted(SRC.rglob("*.py")),
    ids=lambda path: str(path.relative_to(SRC)),
)
def test_no_module_hardcodes_a_model_name(path: Path) -> None:
    """A model name in source is a default that outlives its own correctness."""
    offenders = [value for value in _string_literals(path) if _MODEL_NAME_PATTERN.search(value)]

    assert not offenders, (
        f"{path.relative_to(ROOT)} contains a hardcoded model name: {offenders}. "
        "The model must come from JOB_FINDER_LLM_MODEL."
    )


def test_model_is_required_configuration_with_no_fallback() -> None:
    """Missing configuration must fail loudly at load, not silently at first call."""
    presence = configuration_presence(environment={}, dotenv_path=Path("__absent__.env"))

    assert "JOB_FINDER_LLM_MODEL" in presence.missing
    assert not presence.complete

    with pytest.raises(GatewayProviderError, match="JOB_FINDER_LLM_MODEL"):
        load_gateway_settings(environment={}, dotenv_path=Path("__absent__.env"))


def _settings(model: str) -> AmdGatewaySettings:
    return AmdGatewaySettings(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model=model,
        policy_version="1",
        timeout_seconds=30.0,
        usage_limits=UsageLimits(
            max_requests=10,
            max_estimated_input_tokens=1000,
            max_output_tokens=500,
            max_output_tokens_per_request=100,
        ),
    )


class _StubGateway:
    """Minimal gateway double returning a chosen model ID."""

    def __init__(self, returned_model: str) -> None:
        self.chat = self
        self.completions = self
        self._returned_model = returned_model

    def create(self, **_: Any) -> Any:
        class _Completion:
            model = self._returned_model

        return _Completion()


def test_confirmed_model_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    settings = _settings("configured-model-id")

    with caplog.at_level(logging.INFO, logger="job_finder.matching.openai_client"):
        result = check_gateway_connectivity(settings, client=_StubGateway("configured-model-id"))

    assert result.configured_model == "configured-model-id"
    assert result.returned_model_id == "configured-model-id"
    assert "llm_model_confirmed model=configured-model-id" in caplog.text


def test_substituted_model_is_reported_as_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Gateways alias and substitute. A scan whose results shift because the model
    changed underneath it must be diagnosable from the log alone."""
    settings = _settings("configured-model-id")

    with caplog.at_level(logging.WARNING, logger="job_finder.matching.openai_client"):
        result = check_gateway_connectivity(
            settings, client=_StubGateway("something-else-entirely")
        )

    assert result.configured_model == "configured-model-id"
    assert result.returned_model_id == "something-else-entirely"
    assert "llm_model_mismatch" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_model_change_invalidates_cached_evaluations() -> None:
    """The model is part of the cache key, so swapping it cannot serve stale verdicts."""
    first = _settings("model-a").model_policy
    second = _settings("model-b").model_policy

    assert first != second
    assert first.cache_key != second.cache_key
