"""Minimal OpenAI Responses API adapter with redacted configuration checks."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from job_finder.matching.evaluator import LLMRequest, LLMResponse, ModelPolicy, UsageLimits

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
REQUIRED_ENVIRONMENT_VARIABLES = (
    "OPENAI_API_KEY",
    "JOB_FINDER_LLM_MODEL",
    "JOB_FINDER_LLM_REASONING_EFFORT",
    "JOB_FINDER_LLM_POLICY_VERSION",
    "JOB_FINDER_LLM_MAX_REQUESTS",
    "JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS",
    "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS",
    "JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST",
)
_ALLOWED_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})


class OpenAIProviderError(RuntimeError):
    """A sanitized OpenAI configuration, transport, or response error."""


@dataclass(frozen=True, slots=True)
class ConfigurationPresence:
    """Variable names only; secret values are never retained here."""

    configured: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True, slots=True)
class OpenAIProviderSettings:
    """Validated live-provider settings loaded from environment variables."""

    api_key: str
    base_url: str
    model: str
    reasoning_effort: str
    policy_version: str
    timeout_seconds: float
    usage_limits: UsageLimits

    @property
    def model_policy(self) -> ModelPolicy:
        return ModelPolicy(
            provider="openai",
            model=self.model,
            policy_version=f"reasoning-{self.reasoning_effort}-v{self.policy_version}",
        )


@dataclass(frozen=True, slots=True)
class ConnectivityResult:
    """Non-secret evidence that authentication and model access succeeded."""

    provider: str
    configured_model: str
    returned_model_id: str


UrlOpen = Callable[..., Any]


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


def load_openai_settings(
    *,
    environment: Mapping[str, str] | None = None,
    dotenv_path: Path = Path(".env"),
) -> OpenAIProviderSettings:
    """Load live settings without mutating the process environment."""
    values = _merged_environment(environment, dotenv_path)
    presence = configuration_presence(environment=values, dotenv_path=Path("__absent__.env"))
    if presence.missing:
        raise OpenAIProviderError(
            "missing required environment variables: " + ", ".join(presence.missing)
        )
    reasoning_effort = _required(values, "JOB_FINDER_LLM_REASONING_EFFORT").lower()
    if reasoning_effort not in _ALLOWED_REASONING_EFFORTS:
        raise OpenAIProviderError(
            "JOB_FINDER_LLM_REASONING_EFFORT must be one of: "
            + ", ".join(sorted(_ALLOWED_REASONING_EFFORTS))
        )
    timeout_seconds = _positive_float(
        values.get("JOB_FINDER_LLM_TIMEOUT_SECONDS", "30"), "JOB_FINDER_LLM_TIMEOUT_SECONDS"
    )
    return OpenAIProviderSettings(
        api_key=_required(values, "OPENAI_API_KEY"),
        base_url=DEFAULT_OPENAI_BASE_URL,
        model=_required(values, "JOB_FINDER_LLM_MODEL"),
        reasoning_effort=reasoning_effort,
        policy_version=_required(values, "JOB_FINDER_LLM_POLICY_VERSION"),
        timeout_seconds=timeout_seconds,
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


class OpenAIResponsesClient:
    """Synchronous structured-output client for the OpenAI Responses API."""

    def __init__(
        self,
        settings: OpenAIProviderSettings,
        *,
        opener: UrlOpen = urlopen,
    ) -> None:
        self._settings = settings
        self._opener = opener

    def complete(self, request: LLMRequest, policy: ModelPolicy) -> LLMResponse:
        """Submit one non-stored structured response and return measured usage."""
        if policy != self._settings.model_policy:
            raise OpenAIProviderError("requested model policy does not match provider settings")
        payload = {
            "model": self._settings.model,
            "input": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "reasoning": {"effort": self._settings.reasoning_effort},
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "seniority_decision",
                    "strict": True,
                    "schema": request.response_schema,
                }
            },
        }
        response = _request_json(
            Request(
                f"{self._settings.base_url}/responses",
                data=json.dumps(payload).encode("utf-8"),
                headers=_headers(self._settings.api_key),
                method="POST",
            ),
            timeout_seconds=self._settings.timeout_seconds,
            opener=self._opener,
        )
        usage = _mapping(response.get("usage"), "response.usage")
        return LLMResponse(
            content=_output_text(response),
            input_tokens=_non_negative_int(usage.get("input_tokens"), "usage.input_tokens"),
            output_tokens=_non_negative_int(usage.get("output_tokens"), "usage.output_tokens"),
        )


def check_openai_connectivity(
    settings: OpenAIProviderSettings,
    *,
    opener: UrlOpen = urlopen,
) -> ConnectivityResult:
    """Verify authentication and configured-model access without generating tokens."""
    model_id = quote(settings.model, safe="")
    response = _request_json(
        Request(
            f"{settings.base_url}/models/{model_id}",
            headers=_headers(settings.api_key),
            method="GET",
        ),
        timeout_seconds=settings.timeout_seconds,
        opener=opener,
    )
    returned_id = response.get("id")
    if not isinstance(returned_id, str) or not returned_id.strip():
        raise OpenAIProviderError("connectivity response did not contain a model ID")
    return ConnectivityResult(
        provider="openai",
        configured_model=settings.model,
        returned_model_id=returned_id,
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
            raise OpenAIProviderError(f"invalid .env assignment on line {line_number}")
        name, raw_value = line.split("=", maxsplit=1)
        name = name.strip()
        if not name or not name.replace("_", "a").isalnum():
            raise OpenAIProviderError(f"invalid .env variable name on line {line_number}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _request_json(
    request: Request,
    *,
    timeout_seconds: float,
    opener: UrlOpen,
) -> Mapping[str, object]:
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except HTTPError as error:
        raise OpenAIProviderError(f"OpenAI API returned HTTP {error.code}") from error
    except (TimeoutError, URLError) as error:
        raise OpenAIProviderError("OpenAI API connection failed") from error
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OpenAIProviderError("OpenAI API returned invalid JSON") from error
    return _mapping(parsed, "response")


def _output_text(response: Mapping[str, object]) -> str:
    output = response.get("output")
    if not isinstance(output, list):
        raise OpenAIProviderError("OpenAI response.output must be an array")
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text
            if isinstance(part, Mapping) and part.get("type") == "refusal":
                raise OpenAIProviderError("OpenAI model refused the seniority evaluation")
    raise OpenAIProviderError("OpenAI response did not contain output text")


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "job-finder/0.1 public-job-discovery",
    }


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise OpenAIProviderError(f"{path} must be an object")
    return cast(Mapping[str, object], value)


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise OpenAIProviderError(f"{name} must be configured")
    return value


def _positive_int(values: Mapping[str, str], name: str) -> int:
    raw = _required(values, name)
    try:
        value = int(raw)
    except ValueError as error:
        raise OpenAIProviderError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise OpenAIProviderError(f"{name} must be a positive integer")
    return value


def _positive_float(raw: str, name: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise OpenAIProviderError(f"{name} must be a positive number") from error
    if value <= 0:
        raise OpenAIProviderError(f"{name} must be a positive number")
    return value


def _non_negative_int(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OpenAIProviderError(f"{path} must be a non-negative integer")
    return value
