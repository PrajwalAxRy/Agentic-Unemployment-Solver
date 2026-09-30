"""AMD Unified LLM gateway adapter using the OpenAI-compatible Python client."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import OpenAI, OpenAIError

from job_finder.cost import TokenRates, load_rates
from job_finder.matching.evaluator import (
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    ModelPolicy,
    UsageLimits,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_GATEWAY_BASE_URL = "https://llm-api.amd.com/Unified/v1"
REQUIRED_ENVIRONMENT_VARIABLES = (
    "LLM_GATEWAY_KEY",
    "JOB_FINDER_LLM_MODEL",
    "JOB_FINDER_LLM_POLICY_VERSION",
    "JOB_FINDER_LLM_MAX_REQUESTS",
    "JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS",
    "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS",
    "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST",
)


class GatewayProviderError(LLMProviderError):
    """A sanitized gateway configuration, transport, or response error."""


@dataclass(frozen=True, slots=True)
class ConfigurationPresence:
    """Variable names only; secret values are never retained here."""

    configured: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True, slots=True)
class AmdGatewaySettings:
    """Validated AMD gateway settings loaded from environment variables."""

    api_key: str = field(repr=False)
    base_url: str
    model: str
    policy_version: str
    timeout_seconds: float
    usage_limits: UsageLimits
    token_rates: TokenRates | None = None
    """Per-million-token prices, or None when they are not configured.

    Optional on purpose: a missing rate means cost is reported as unknown, never as zero.
    """

    @property
    def model_policy(self) -> ModelPolicy:
        return ModelPolicy(
            provider="amd-llm-gateway",
            model=self.model,
            policy_version=f"v{self.policy_version}",
        )


@dataclass(frozen=True, slots=True)
class ConnectivityResult:
    """Non-secret evidence that gateway authentication and inference succeeded."""

    provider: str
    configured_model: str
    returned_model_id: str


def configuration_presence(
    *,
    environment: Mapping[str, str] | None = None,
    dotenv_path: Path = Path(".env"),
) -> ConfigurationPresence:
    """Report only required variable names that are present or missing."""
    values = _merged_environment(environment, dotenv_path)
    configured = tuple(
        name for name in REQUIRED_ENVIRONMENT_VARIABLES if values.get(name, "").strip()
    )
    missing = tuple(name for name in REQUIRED_ENVIRONMENT_VARIABLES if name not in configured)
    return ConfigurationPresence(configured=configured, missing=missing)


def load_gateway_settings(
    *,
    environment: Mapping[str, str] | None = None,
    dotenv_path: Path = Path(".env"),
) -> AmdGatewaySettings:
    """Load gateway settings without mutating the process environment."""
    values = _merged_environment(environment, dotenv_path)
    presence = configuration_presence(environment=values, dotenv_path=Path("__absent__.env"))
    if presence.missing:
        raise GatewayProviderError(
            "missing required environment variables: " + ", ".join(presence.missing)
        )
    return AmdGatewaySettings(
        api_key=_required(values, "LLM_GATEWAY_KEY"),
        base_url=DEFAULT_GATEWAY_BASE_URL,
        model=_required(values, "JOB_FINDER_LLM_MODEL"),
        policy_version=_required(values, "JOB_FINDER_LLM_POLICY_VERSION"),
        timeout_seconds=_positive_float(
            values.get("JOB_FINDER_LLM_TIMEOUT_SECONDS", "30"),
            "JOB_FINDER_LLM_TIMEOUT_SECONDS",
        ),
        token_rates=load_rates(values),
        usage_limits=UsageLimits(
            max_requests=_positive_int(values, "JOB_FINDER_LLM_MAX_REQUESTS"),
            max_estimated_input_tokens=_positive_int(
                values, "JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS"
            ),
            max_output_tokens=_positive_int(values, "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS"),
            max_output_tokens_per_request=_positive_int(
                values, "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST"
            ),
        ),
    )


class AmdGatewayClient:
    """Provider-neutral evaluator adapter backed by AMD gateway Chat Completions."""

    def __init__(
        self,
        settings: AmdGatewaySettings,
        *,
        client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or _gateway_client(settings)

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        """Submit one strict Chat Completion and return measured gateway usage."""
        if policy != self._settings.model_policy:
            raise GatewayProviderError("requested model policy does not match gateway settings")
        try:
            completion = self._client.chat.completions.create(
                model=self._settings.model,
                messages=[
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        # Derived from the schema's own required fields rather than a fixed
                        # literal. Previously hardcoded to "seniority_decision" even for the
                        # merged relevance+seniority+location schema, which is misleading in
                        # gateway-side logs/telemetry once both evaluators are in use.
                        "name": _schema_name(request.response_schema),
                        "strict": True,
                        "schema": dict(request.response_schema),
                    },
                },
                max_tokens=request.max_output_tokens,
            )
        except OpenAIError as error:
            raise GatewayProviderError("AMD LLM gateway request failed") from error

        if not completion.choices:
            raise GatewayProviderError("AMD LLM gateway returned no completion choices")
        content = completion.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise GatewayProviderError("AMD LLM gateway returned no completion text")
        usage = completion.usage
        if usage is None:
            raise GatewayProviderError("AMD LLM gateway returned no token usage")
        return LLMResponse(
            content=content,
            input_tokens=_non_negative_int(usage.prompt_tokens, "usage.prompt_tokens"),
            output_tokens=_non_negative_int(
                usage.completion_tokens,
                "usage.completion_tokens",
            ),
        )


def check_gateway_connectivity(
    settings: AmdGatewaySettings,
    *,
    client: Any | None = None,
) -> ConnectivityResult:
    """Verify gateway authentication and model routing with a minimal completion."""
    gateway = client or _gateway_client(settings)
    try:
        completion = gateway.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": "Reply OK."}],
            max_tokens=16,
        )
    except OpenAIError as error:
        raise GatewayProviderError("AMD LLM gateway connectivity check failed") from error
    returned_model = completion.model
    if not isinstance(returned_model, str) or not returned_model.strip():
        raise GatewayProviderError("gateway connectivity response did not contain a model ID")
    # Log both IDs. The model is configuration (JOB_FINDER_LLM_MODEL), never hardcoded, so
    # the only way to know what actually answered is to record what the gateway returned.
    # Gateways routinely alias or silently substitute, and a scan whose results shifted
    # because the model changed underneath it should be diagnosable from the log alone.
    #
    # Two distinct cases, deliberately logged at different levels. Observed live: the
    # gateway resolves "gpt-5.6-luna" to the dated pin "gpt-5.6-luna-2026-07-09". That is
    # a *more specific* answer to the same request and is routine, so it is INFO -- raising
    # a WARNING on every single run would train the reader to ignore the one that matters.
    # A genuinely different model is a different matter and stays at WARNING.
    resolved = returned_model.strip()
    if resolved == settings.model:
        _LOGGER.info("llm_model_confirmed model=%s", settings.model)
    elif resolved.startswith(settings.model):
        _LOGGER.info(
            "llm_model_pinned configured=%s resolved=%s",
            settings.model,
            resolved,
        )
    else:
        _LOGGER.warning(
            "llm_model_mismatch configured=%s returned=%s",
            settings.model,
            resolved,
        )
    return ConnectivityResult(
        provider="amd-llm-gateway",
        configured_model=settings.model,
        returned_model_id=returned_model,
    )


def _schema_name(response_schema: Mapping[str, object]) -> str:
    """Name the response_format schema from its own required fields.

    "seniority_decision" for the single-purpose schema, "merged_relevance_seniority"
    (optionally with "_location") for the merged schema -- distinguishable in gateway
    logs without hardcoding either evaluator's shape here.
    """
    required = response_schema.get("required")
    fields = set(required) if isinstance(required, (list, tuple)) else set()
    if "relevance" in fields:
        return (
            "merged_relevance_seniority_location"
            if "location_eligible" in fields
            else "merged_relevance_seniority"
        )
    return "seniority_decision"


def _gateway_client(settings: AmdGatewaySettings) -> OpenAI:
    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        default_headers={"Ocp-Apim-Subscription-Key": settings.api_key},
        timeout=settings.timeout_seconds,
        max_retries=0,
    )


def _merged_environment(
    environment: Mapping[str, str] | None,
    dotenv_path: Path,
) -> dict[str, str]:
    values = _load_dotenv(dotenv_path)
    values.update(os.environ if environment is None else environment)
    return values


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise GatewayProviderError(f"invalid .env assignment on line {line_number}")
        name, raw_value = line.split("=", maxsplit=1)
        name = name.strip()
        if not name or not name.replace("_", "a").isalnum():
            raise GatewayProviderError(f"invalid .env variable name on line {line_number}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise GatewayProviderError(f"{name} must be configured")
    return value


def _positive_int(values: Mapping[str, str], name: str) -> int:
    raw = _required(values, name)
    try:
        value = int(raw)
    except ValueError as error:
        raise GatewayProviderError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise GatewayProviderError(f"{name} must be a positive integer")
    return value


def _positive_float(raw: str, name: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise GatewayProviderError(f"{name} must be a positive number") from error
    if value <= 0:
        raise GatewayProviderError(f"{name} must be a positive number")
    return value


def _non_negative_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GatewayProviderError(f"{path} must be a non-negative integer")
    return value
