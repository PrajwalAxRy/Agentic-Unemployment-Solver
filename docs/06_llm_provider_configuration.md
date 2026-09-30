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

The configured model is settled (`docs/decisions.md`); do not relitigate it without new evidence.
If quality ever misses the bar, compare the gateway's larger tiers on the same labelled inputs
rather than adding company-specific prompt exceptions.

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

The request and token ceilings are enforced locally, **per run** — `UsageBudget` is rebuilt on each
invocation, so these are per-scan ceilings and not a monthly allowance. Sizing and the reasoning
behind the current values are in `docs/decisions.md` D4. The OpenAI client disables automatic
transport retries so the application's request counter remains a truthful upper bound;
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

The repository additionally supplies the response JSON schema, output-token ceiling, timeout, and
sanitized usage accounting.

Two prompts exist. `config/merged_prompt.toml` is the default: one call per job returning relevance,
seniority, and conditionally location, each with its own verbatim evidence quote.
`config/seniority_prompt.toml` is the single-purpose fallback, reachable with `--seniority-only`.
Note that toggling that flag changes `prompt_version`, which invalidates every cached verdict and
re-evaluates the whole corpus.

## Cost accounting

Each completed scan prices its own measured token usage and appends to `state/llm_costs.jsonl`;
`job-finder costs` reads it back as a per-day table.

```
JOB_FINDER_LLM_INPUT_COST_PER_MTOK=0.20
JOB_FINDER_LLM_OUTPUT_COST_PER_MTOK=1.20
JOB_FINDER_LLM_COST_CURRENCY=USD
```

Rates live here rather than in code because model prices move and a gateway may not bill list price
(`docs/decisions.md` D7). **If these are unset, cost is reported as unknown — never as zero.** Both
are required together.

Measured on 2026-09-30: ~7,143 input tokens and up to 300 output tokens per job, about **$0.0020 a
job**, roughly **$7.23** for a full 3,677-job scan. If the gateway's actual chargeback differs,
correct the two rates; past ledger entries stay as they were recorded.

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

## H9 guarded quality validation

Run the reviewed evaluation set, complete deterministic company gate, and bounded unseen batch:

```powershell
uv run --locked job-finder validate-seniority --live-limit 8
```

The command writes generated machine-readable evidence to the ignored
`reports/phase8_seniority_validation.json` and the human checkpoint artifact to
`docs/reviews/h9_seniority_quality_review.md`. Console output contains only aggregate counts and
token usage.

After a prompt-only correction, refresh the exact selected public jobs while reusing the completed
full-registry coverage evidence:

```powershell
uv run --locked job-finder validate-seniority --live-limit 8 `
  --reuse-live-from reports/phase8_seniority_validation.json
```

Reuse does not skip model evaluation. It reruns the complete reviewed set, reloads each selected
job from its approved source adapter, retrieves its current public description, and evaluates the
same URLs under the current prompt and model policy.
