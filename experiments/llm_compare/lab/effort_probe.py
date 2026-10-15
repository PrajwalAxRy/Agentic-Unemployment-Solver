"""Which reasoning_effort values does the gateway accept, per model?

  uv run --locked python experiments/llm_compare/lab/effort_probe.py

One tiny request per (model, effort). Prints status, the server's error text (never
request headers or keys), latency and the reasoning-token count. Costs well under a cent.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402
from openai import OpenAIError  # noqa: E402

from job_finder.matching.openai_client import _gateway_client, load_gateway_settings  # noqa: E402

EFFORTS = [None, "none", "minimal", "low", "medium", "high", "xhigh", "not-a-level"]
PROMPT = (
    "A bat and a ball cost 1.10 in total. The bat costs 1.00 more than the ball. "
    "How much does the ball cost? Answer with the number only."
)

for model in ("luna", "sol"):
    env = {**os.environ, **lab._env_file(lab.PROFILES[model])}
    settings = load_gateway_settings(environment=env)
    client = _gateway_client(settings)
    print(f"\n== {model} ({settings.model})")
    for effort in EFFORTS:
        extra = {} if effort is None else {"reasoning_effort": effort}
        started = time.monotonic()
        try:
            completion = client.chat.completions.create(
                model=settings.model,
                messages=[{"role": "user", "content": PROMPT}],
                max_tokens=4000,
                **extra,
            )
            usage = completion.usage
            details = getattr(usage, "completion_tokens_details", None)
            reasoning = getattr(details, "reasoning_tokens", None) if details else None
            answer = (completion.choices[0].message.content or "").strip()[:20]
            print(
                f"  {str(effort):12s} OK    {time.monotonic() - started:5.1f}s "
                f"out={usage.completion_tokens:5d} reasoning={reasoning} answer={answer!r}"
            )
        except OpenAIError as error:
            status = getattr(error, "status_code", "?")
            body = getattr(error, "body", None) or str(error)
            print(
                f"  {str(effort):12s} ERROR {time.monotonic() - started:5.1f}s "
                f"status={status} {str(body)[:600]}"
            )
