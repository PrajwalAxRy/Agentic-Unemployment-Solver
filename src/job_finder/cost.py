"""Per-run LLM cost, computed from provider-reported token usage.

Every scan already records ``measured_input_tokens`` and ``measured_output_tokens`` -- the
counts the provider itself returned, not local estimates. Multiplying those by a rate turns
a token figure nobody reads into a number that answers "what does this cost me a day".

Rates are configuration, never a constant baked into the code. Model prices move -- the
budget tier this project uses fell 80% in a single month during 2026 -- and a gateway or
reseller may not bill list price at all, so a hardcoded table would go stale silently and
produce confidently wrong money. When no rate is configured the cost is reported as
*unknown* rather than zero: a run that genuinely cost nothing and a run whose price we
cannot compute must not look identical.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

TOKENS_PER_MILLION = 1_000_000

INPUT_RATE_VARIABLE = "JOB_FINDER_LLM_INPUT_COST_PER_MTOK"
OUTPUT_RATE_VARIABLE = "JOB_FINDER_LLM_OUTPUT_COST_PER_MTOK"
CURRENCY_VARIABLE = "JOB_FINDER_LLM_COST_CURRENCY"


@dataclass(frozen=True, slots=True)
class TokenRates:
    """What one million input and output tokens cost, in ``currency``."""

    input_per_mtok: float
    output_per_mtok: float
    currency: str = "USD"

    def cost_of(self, *, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        ) / TOKENS_PER_MILLION


@dataclass(frozen=True, slots=True)
class RunCost:
    """One run's token usage priced up, plus the unit economics worth tracking.

    ``per_evaluated_job`` is the number to watch over time. Total cost mostly tracks how
    many new postings appeared that day, so it says little on its own; cost per job moves
    only when the prompt, the model, or description length changes -- which is exactly the
    kind of drift worth noticing.
    """

    run_id: str
    completed_at: str
    model_policy: str
    prompt_version: str
    evaluated: int
    cache_hits: int
    request_count: int
    input_tokens: int
    output_tokens: int
    currency: str
    input_cost: float | None
    output_cost: float | None
    total_cost: float | None

    @property
    def priced(self) -> bool:
        """Whether rates were configured, so the money figures mean anything."""
        return self.total_cost is not None

    @property
    def per_evaluated_job(self) -> float | None:
        if self.total_cost is None or self.evaluated <= 0:
            return None
        return self.total_cost / self.evaluated

    def as_json(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "completed_at": self.completed_at,
            "model_policy": self.model_policy,
            "prompt_version": self.prompt_version,
            "evaluated": self.evaluated,
            "cache_hits": self.cache_hits,
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "currency": self.currency,
            "input_cost": _rounded(self.input_cost),
            "output_cost": _rounded(self.output_cost),
            "total_cost": _rounded(self.total_cost),
            "cost_per_evaluated_job": _rounded(self.per_evaluated_job, digits=6),
        }


def load_rates(values: dict[str, str]) -> TokenRates | None:
    """Read rates from configuration, or ``None`` when they are not set.

    Both rates must be present together. Pricing input but not output would silently
    under-report every run, and a half-priced number is more dangerous than no number
    because it still looks authoritative.
    """
    raw_input = (values.get(INPUT_RATE_VARIABLE) or "").strip()
    raw_output = (values.get(OUTPUT_RATE_VARIABLE) or "").strip()
    if not raw_input or not raw_output:
        return None
    return TokenRates(
        input_per_mtok=_rate(raw_input, INPUT_RATE_VARIABLE),
        output_per_mtok=_rate(raw_output, OUTPUT_RATE_VARIABLE),
        currency=(values.get(CURRENCY_VARIABLE) or "USD").strip() or "USD",
    )


def price_run(
    *,
    run_id: str,
    completed_at: str,
    model_policy: str,
    prompt_version: str,
    evaluated: int,
    cache_hits: int,
    request_count: int,
    input_tokens: int,
    output_tokens: int,
    rates: TokenRates | None,
) -> RunCost:
    """Attach cost to one run's measured usage, leaving it unpriced if rates are absent."""
    input_cost = None if rates is None else input_tokens * rates.input_per_mtok / TOKENS_PER_MILLION
    output_cost = (
        None if rates is None else output_tokens * rates.output_per_mtok / TOKENS_PER_MILLION
    )
    return RunCost(
        run_id=run_id,
        completed_at=completed_at,
        model_policy=model_policy,
        prompt_version=prompt_version,
        evaluated=evaluated,
        cache_hits=cache_hits,
        request_count=request_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        currency="USD" if rates is None else rates.currency,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=None if rates is None else (input_cost or 0.0) + (output_cost or 0.0),
    )


def format_cost_line(cost: RunCost) -> str:
    """One terminal line summarising what the run spent."""
    if not cost.priced:
        return (
            f"llm_cost=unavailable tokens_in={cost.input_tokens} "
            f"tokens_out={cost.output_tokens} requests={cost.request_count} "
            f"(set {INPUT_RATE_VARIABLE} and {OUTPUT_RATE_VARIABLE} to price runs)"
        )
    per_job = cost.per_evaluated_job
    suffix = "" if per_job is None else f" per_job={cost.currency} {per_job:.4f}"
    return (
        f"llm_cost={cost.currency} {cost.total_cost:.2f} "
        f"evaluated={cost.evaluated} cached={cost.cache_hits} "
        f"tokens_in={cost.input_tokens} tokens_out={cost.output_tokens}{suffix}"
    )


def summarise(history: list[RunCost]) -> dict[str, object]:
    """Aggregate a run history into the totals a daily-cost view needs.

    Unpriced runs are counted but excluded from the money totals, and reported separately,
    so a partially-configured history cannot quietly understate the spend.
    """
    priced = [item for item in history if item.priced and item.total_cost is not None]
    total = sum(item.total_cost or 0.0 for item in priced)
    evaluated = sum(item.evaluated for item in priced)
    days = {item.completed_at[:10] for item in priced if item.completed_at}
    return {
        "runs": len(history),
        "priced_runs": len(priced),
        "unpriced_runs": len(history) - len(priced),
        "currency": priced[0].currency if priced else "USD",
        "total_cost": _rounded(total),
        "total_evaluated": evaluated,
        "mean_cost_per_run": _rounded(total / len(priced)) if priced else None,
        "mean_cost_per_day": _rounded(total / len(days)) if days else None,
        "cost_per_evaluated_job": _rounded(total / evaluated, digits=6) if evaluated else None,
        "distinct_days": len(days),
        # A naive x30 of the mean day would overstate the recurring bill: a first run
        # evaluates the whole backlog, later ones only new postings. Reported so the
        # caller can decide, rather than presenting one number as "your monthly cost".
        "projected_30_day": _rounded(total / len(days) * 30) if days else None,
    }


def _rate(raw: str, name: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {raw!r}") from error
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _rounded(value: float | None, *, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def iso_day(timestamp: str) -> str:
    """The calendar day of an ISO timestamp, or the raw value when unparseable."""
    try:
        return datetime.fromisoformat(timestamp).date().isoformat()
    except ValueError:
        return timestamp[:10]


DEFAULT_LEDGER_PATH = Path("state/llm_costs.jsonl")


def append_to_ledger(cost: RunCost, path: Path) -> None:
    """Append one run to the cost history.

    JSON Lines, opened in append mode, because the alternative -- read the whole file,
    add an entry, rewrite it -- loses the entire history if the process dies mid-write.
    An append either lands or it does not.

    A failure here is logged and swallowed by the caller: cost accounting must never be
    the reason a completed scan reports as failed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(cost.as_json(), ensure_ascii=False) + "\n")


def read_ledger(path: Path) -> list[RunCost]:
    """Load the run history, skipping entries that cannot be parsed.

    Tolerant by design. This file is a record, not an input to any decision, so one
    corrupt line -- a half-written entry from a killed process, say -- must not make the
    remaining history unreadable.
    """
    if not path.exists():
        return []
    history: list[RunCost] = []
    for line in path.read_text("utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            _LOGGER.warning("cost_ledger_line_unreadable path=%s", path)
            continue
        if not isinstance(raw, dict):
            continue
        history.append(
            RunCost(
                run_id=str(raw.get("run_id") or ""),
                completed_at=str(raw.get("completed_at") or ""),
                model_policy=str(raw.get("model_policy") or ""),
                prompt_version=str(raw.get("prompt_version") or ""),
                evaluated=int(raw.get("evaluated") or 0),
                cache_hits=int(raw.get("cache_hits") or 0),
                request_count=int(raw.get("request_count") or 0),
                input_tokens=int(raw.get("input_tokens") or 0),
                output_tokens=int(raw.get("output_tokens") or 0),
                currency=str(raw.get("currency") or "USD"),
                input_cost=_optional_float(raw.get("input_cost")),
                output_cost=_optional_float(raw.get("output_cost")),
                total_cost=_optional_float(raw.get("total_cost")),
            )
        )
    return history


def daily_totals(history: list[RunCost]) -> list[dict[str, object]]:
    """Collapse the history into one row per calendar day, oldest first."""
    days: dict[str, dict[str, object]] = {}
    for item in history:
        key = iso_day(item.completed_at)
        day = days.setdefault(
            key, {"day": key, "runs": 0, "evaluated": 0, "cost": 0.0, "currency": item.currency}
        )
        day["runs"] = int(day["runs"]) + 1  # type: ignore[call-overload]
        day["evaluated"] = int(day["evaluated"]) + item.evaluated  # type: ignore[call-overload]
        day["cost"] = float(day["cost"]) + (item.total_cost or 0.0)  # type: ignore[arg-type]
    for day in days.values():
        day["cost"] = round(float(day["cost"]), 4)  # type: ignore[arg-type]
    return [days[key] for key in sorted(days)]


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
