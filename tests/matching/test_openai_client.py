"""Tests for redacted OpenAI configuration and Responses API adaptation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from job_finder.matching.evaluator import LLMRequest
from job_finder.matching.openai_client import (
    REQUIRED_ENVIRONMENT_VARIABLES,
    OpenAIProviderError,
    OpenAIResponsesClient,
    check_openai_connectivity,
    configuration_presence,
    load_openai_settings,
)


def configured_environment() -> dict[str, str]:
    return {
        "OPENAI_API_KEY": "test-secret",
        "JOB_FINDER_LLM_MODEL": "gpt-6-luna",
        "JOB_FINDER_LLM_REASONING_EFFORT": "low",
        "JOB_FINDER_LLM_POLICY_VERSION": "1",
        "JOB_FINDER_LLM_MAX_REQUESTS": "500",
        "JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS": "1000000",
        "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS": "100000",
        "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST": "300",
    }


@dataclass
class FakeResponse:
    payload: dict[str, object]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class RecordingOpener:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.requests: list[Any] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Any, *, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeResponse(self.responses.pop(0))


def test_presence_reports_names_without_secret_values(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=super-secret\n", encoding="utf-8")

    presence = configuration_presence(environment={}, dotenv_path=dotenv)

    assert presence.configured == ("OPENAI_API_KEY",)
    assert set(presence.missing) == set(REQUIRED_ENVIRONMENT_VARIABLES) - {"OPENAI_API_KEY"}
    assert "super-secret" not in repr(presence)


def test_environment_overrides_dotenv_and_loads_limits(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("JOB_FINDER_LLM_MODEL=wrong-model\n", encoding="utf-8")

    settings = load_openai_settings(
        environment=configured_environment(),
        dotenv_path=dotenv,
    )

    assert settings.model == "gpt-6-luna"
    assert settings.reasoning_effort == "low"
    assert settings.usage_limits.max_requests == 500
    assert settings.model_policy.cache_key == "openai:gpt-6-luna:reasoning-low-v1"


def test_missing_configuration_error_contains_names_not_values() -> None:
    with pytest.raises(OpenAIProviderError, match="JOB_FINDER_LLM_MODEL") as captured:
        load_openai_settings(environment={"OPENAI_API_KEY": "secret"})

    assert "secret" not in str(captured.value)


def test_connectivity_uses_model_endpoint_without_generating_tokens() -> None:
    settings = load_openai_settings(environment=configured_environment())
    opener = RecordingOpener([{"id": "gpt-6-luna", "object": "model"}])

    result = check_openai_connectivity(settings, opener=opener)

    request = opener.requests[0]
    assert request.full_url.endswith("/models/gpt-6-luna")
    assert request.method == "GET"
    assert result.returned_model_id == "gpt-6-luna"


def test_responses_client_sends_strict_nonstored_schema_and_reads_usage() -> None:
    settings = load_openai_settings(environment=configured_environment())
    opener = RecordingOpener(
        [
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"ok":true}'}],
                    }
                ],
                "usage": {"input_tokens": 45, "output_tokens": 12},
            }
        ]
    )
    client = OpenAIResponsesClient(settings, opener=opener)
    request = LLMRequest(
        system_prompt="System",
        user_prompt="User",
        response_schema={"type": "object"},
        max_output_tokens=300,
    )

    response = client.complete(request, settings.model_policy)

    sent = json.loads(opener.requests[0].data)
    assert sent["model"] == "gpt-6-luna"
    assert sent["reasoning"] == {"effort": "low"}
    assert sent["store"] is False
    assert sent["text"]["format"] == {
        "type": "json_schema",
        "name": "seniority_decision",
        "strict": True,
        "schema": {"type": "object"},
    }
    assert response.content == '{"ok":true}'
    assert response.input_tokens == 45
    assert response.output_tokens == 12
