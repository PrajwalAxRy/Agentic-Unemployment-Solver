# Live LLM provider configuration

## H8 gateway configuration

Use AMD's Unified LLM gateway through the OpenAI Python client:

- Base URL: `https://llm-api.amd.com/Unified/v1`
- Credential variable: `LLM_GATEWAY_KEY`
- Authentication: the key is supplied both as `api_key` and as the
  `Ocp-Apim-Subscription-Key` default header.
- Endpoint: OpenAI-compatible Chat Completions.
- Initial model: `gpt-5.6-luna`.
- Output: strict JSON Schema when supported by the gateway, followed by mandatory local schema and
  verbatim-evidence validation in all cases.

The initial model is a starting policy, not an approved quality baseline. Phase 8 must run the
reviewed evaluation set and a small unseen batch before H9 can approve it. If the model misses the
quality threshold, compare the gateway's `gpt-5.6-terra` and `gpt-5.6-sol` options on the same
labelled inputs rather than adding company-specific prompt exceptions.

The AMD endpoint, header, credential name, and available gateway model names are internal
configuration supplied by the user. The public OpenAI documentation establishes the compatible
Chat Completions and JSON-schema request shapes, but does not document AMD gateway availability,
pricing, retention, or model routing:

- [Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

## Variables and guardrails

Copy `.env.example` to `.env` and configure `LLM_GATEWAY_KEY`. Do not commit `.env`, and do not
paste the key into chat, logs, reports, or command arguments. The application reads `.env` locally
while allowing process environment variables to override it.

The fixed corporate endpoint and non-secret defaults are:

- `https://llm-api.amd.com/Unified/v1`
- `JOB_FINDER_LLM_MODEL=gpt-5.6-luna`
- `JOB_FINDER_LLM_POLICY_VERSION=1`
- `JOB_FINDER_LLM_MAX_REQUESTS=500`
- `JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS=1000000`
- `JOB_FINDER_LLM_MAX_OUTPUT_TOKENS=100000`
- `JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST=300`
- `JOB_FINDER_LLM_TIMEOUT_SECONDS=30`

The request and token ceilings are enforced locally. No monetary estimate is claimed because the
corporate gateway's pricing or chargeback policy has not been provided. The OpenAI client disables
automatic transport retries so the application's request counter remains a truthful upper bound;
the evaluator still performs its one explicit retry for invalid model output.

The provider sends only the approved target definition, public job title, and public job
description. It does not send company-seed provenance, local history, personal profile data, API
secrets, or other repository content.

## Client shape

The production client follows the corporate pattern:

```python
client = OpenAI(
    base_url="https://llm-api.amd.com/Unified/v1",
    api_key=os.environ["LLM_GATEWAY_KEY"],
    default_headers={
        "Ocp-Apim-Subscription-Key": os.environ["LLM_GATEWAY_KEY"],
    },
)

response = client.chat.completions.create(
    model="gpt-5.6-luna",
    messages=[...],
)
```

The repository additionally supplies the seniority JSON schema, output-token ceiling, timeout, and
sanitized usage accounting.

## Redacted checks

Check variable presence without displaying values or using the network:

```powershell
uv run --locked job-finder check-llm --presence-only
```

After configuration, verify authentication and model routing:

```powershell
uv run --locked job-finder check-llm
```

The connectivity command makes one minimal Chat Completion capped at 16 output tokens, the lowest
limit confirmed to work with the AMD gateway, and prints only variable names, provider name, and
model IDs. It never prints the key, prompt response, or request headers. If access fails, request
the necessary AMD gateway entitlement through the approved corporate process.
