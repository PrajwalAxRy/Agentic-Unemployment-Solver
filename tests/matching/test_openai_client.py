"""Tests for redacted AMD Unified LLM gateway configuration and adaptation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import job_finder.matching.openai_client as gateway_module
from job_finder.matching.evaluator import LLMRequest
from job_finder.matching.openai_client import (
    REQUIRED_ENVIRONMENT_VARIABLES,
    AmdGatewayClient,
    GatewayProviderError,
    check_gateway_connectivity,
    configuration_presence,
    load_gateway_settings,
)


def configured_environment() -> dict[str, str]:
    return {
        "LLM_GATEWAY_KEY": "test-secret",
        "JOB_FINDER_LLM_MODEL": "gpt-5.6-luna",
        "JOB_FINDER_LLM_POLICY_VERSION": "1",
        "JOB_FINDER_LLM_MAX_REQUESTS": "500",
        "JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS": "1000000",
        "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS": "100000",
        "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST": "300",
    }


def completion(*, content: str = '{"ok":true}', model: str = "gpt-5.6-luna") -> Any:
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=45, completion_tokens=12),
    )


def fake_client(*responses: Any) -> tuple[Any, MagicMock]:
    create = MagicMock(side_effect=list(responses))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, create


def test_presence_reports_names_without_secret_values(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("LLM_GATEWAY_KEY=super-secret\n", encoding="utf-8")

    presence = configuration_presence(environment={}, dotenv_path=dotenv)

    assert presence.configured == ("LLM_GATEWAY_KEY",)
    assert set(presence.missing) == set(REQUIRED_ENVIRONMENT_VARIABLES) - {"LLM_GATEWAY_KEY"}
    assert "super-secret" not in repr(presence)


def test_environment_overrides_dotenv_and_loads_limits(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("JOB_FINDER_LLM_MODEL=wrong-model\n", encoding="utf-8")

    settings = load_gateway_settings(
        environment=configured_environment(),
        dotenv_path=dotenv,
    )

    assert settings.model == "gpt-5.6-luna"
    assert settings.base_url == "https://llm-api.amd.com/Unified/v1"
    assert settings.usage_limits.max_requests == 500
    assert settings.model_policy.cache_key == "amd-llm-gateway:gpt-5.6-luna:v1"
    assert "test-secret" not in repr(settings)


def test_missing_configuration_error_contains_names_not_values(tmp_path: Path) -> None:
    with pytest.raises(GatewayProviderError, match="JOB_FINDER_LLM_MODEL") as captured:
        load_gateway_settings(
            environment={"LLM_GATEWAY_KEY": "secret"},
            dotenv_path=tmp_path / ".env",
        )

    assert "secret" not in str(captured.value)


def test_sdk_client_uses_gateway_key_for_bearer_and_subscription_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_gateway_settings(environment=configured_environment())
    constructor = MagicMock(return_value=SimpleNamespace())
    monkeypatch.setattr(gateway_module, "OpenAI", constructor)

    AmdGatewayClient(settings)

    constructor.assert_called_once_with(
        base_url="https://llm-api.amd.com/Unified/v1",
        api_key="test-secret",
        default_headers={"Ocp-Apim-Subscription-Key": "test-secret"},
        timeout=30.0,
        max_retries=0,
    )


def test_connectivity_uses_gateway_compatible_chat_completion_limit() -> None:
    settings = load_gateway_settings(environment=configured_environment())
    client, create = fake_client(completion())

    result = check_gateway_connectivity(settings, client=client)

    create.assert_called_once_with(
        model="gpt-5.6-luna",
        messages=[{"role": "user", "content": "Reply OK."}],
        max_tokens=16,
    )
    assert result.provider == "amd-llm-gateway"
    assert result.returned_model_id == "gpt-5.6-luna"


def test_chat_client_sends_strict_schema_and_reads_usage() -> None:
    settings = load_gateway_settings(environment=configured_environment())
    client, create = fake_client(completion())
    provider = AmdGatewayClient(settings, client=client)
    request = LLMRequest(
        system_prompt="System",
        user_prompt="User",
        response_schema={"type": "object"},
        max_output_tokens=300,
    )

    response = provider.complete(request, settings.model_policy)

    create.assert_called_once_with(
        model="gpt-5.6-luna",
        messages=[
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User"},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "seniority_decision",
                "strict": True,
                "schema": {"type": "object"},
            },
        },
        max_tokens=300,
    )
    assert response.content == '{"ok":true}'
    assert response.input_tokens == 45
    assert response.output_tokens == 12


def test_malformed_completion_keeps_provider_usage():
    settings = load_gateway_settings(environment=configured_environment())
    malformed = completion()
    malformed.choices = []
    client, _ = fake_client(malformed)
    gateway = AmdGatewayClient(settings, client=client)
    with pytest.raises(GatewayProviderError) as captured:
        gateway.complete(LLMRequest("system", "user", {}, 100), settings.model_policy)
    assert captured.value.response.input_tokens == 45
    assert captured.value.response.output_tokens == 12
