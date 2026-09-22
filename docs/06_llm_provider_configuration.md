# Live LLM provider configuration

## H8 recommendation

Use the OpenAI Responses API with `gpt-6-luna`, `reasoning.effort=low`, strict Structured
Outputs, and `store=false`.

This is a starting policy, not an approved quality baseline. OpenAI documents GPT-6 Luna as its
most efficient model for focused, high-volume tasks and lists Structured Outputs as supported.
The official model-selection guidance recommends comparing models on the same inputs and retaining
the lightest option that meets the quality bar. Phase 8 therefore runs the reviewed evaluation set
and a small unseen batch before H9 can approve this policy.

Official references:

- [GPT-6 Luna model and current token pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [OpenAI model-selection guidance](https://developers.openai.com/api/docs/guides/model-selection)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses API create reference](https://developers.openai.com/api/reference/resources/responses/methods/create)

The model page currently lists standard text-token prices of USD 0.10 per million input tokens and
USD 0.50 per million output tokens. Pricing, account access, taxes, processing tiers, and regional
premiums can change; confirm them in the OpenAI API dashboard before increasing the checked-in
guardrails.

## Variables and guardrails

Copy `.env.example` to `.env` and configure `OPENAI_API_KEY`. Do not commit `.env`, and do not paste
the key into chat, logs, reports, or command arguments. The application reads `.env` locally while
allowing process environment variables to override it.

The required non-secret policy variables are:

- `JOB_FINDER_LLM_MODEL=gpt-6-luna`
- `JOB_FINDER_LLM_REASONING_EFFORT=low`
- `JOB_FINDER_LLM_POLICY_VERSION=1`
- `JOB_FINDER_LLM_MAX_REQUESTS=500`
- `JOB_FINDER_LLM_MAX_ESTIMATED_INPUT_TOKENS=1000000`
- `JOB_FINDER_LLM_MAX_OUTPUT_TOKENS=100000`
- `JOB_FINDER_LLM_MAX_OUTPUT_TOKENS_PER_REQUEST=300`

The provider endpoint is fixed to the official `https://api.openai.com/v1` API, and
`JOB_FINDER_LLM_TIMEOUT_SECONDS` defaults to 30. The default token ceilings correspond to about
USD 0.15 at the model page's current standard rates if both input and output ceilings are fully
consumed. Request and token ceilings are enforced in process; the API project should also have an
appropriate platform spend limit.

The provider sends only the approved target definition, job title, and public job description. It
does not send company seed provenance, local history, personal profile data, API secrets, or other
repository content. Responses use strict JSON Schema and are submitted with `store=false`.

## Redacted checks

Check variable presence without displaying values or using the network:

```powershell
uv run --locked job-finder check-llm --presence-only
```

After configuration, verify authentication and access to the configured model without generating a
model response:

```powershell
uv run --locked job-finder check-llm
```

The connectivity command performs an authenticated model metadata request and prints only variable
names, provider name, and model IDs. A working ChatGPT subscription does not necessarily provide
API billing or model access; if the check fails for account access, an OpenAI API project owner must
enable billing/access or provide an approved project key through the local `.env` file.
