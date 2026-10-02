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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

TOKENS_PER_MILLION = 1_000_000

INPUT_RATE_VARIABLE = "JOB_FINDER_LLM_INPUT_COST_PER_MTOK"
OUTPUT_RATE_VARIABLE = "JOB_FINDER_LLM_OUTPUT_COST_PER_MTOK"
CACHED_INPUT_RATE_VARIABLE = "JOB_FINDER_LLM_CACHED_INPUT_COST_PER_MTOK"
CACHE_WRITE_RATE_VARIABLE = "JOB_FINDER_LLM_CACHE_WRITE_COST_PER_MTOK"
CURRENCY_VARIABLE = "JOB_FINDER_LLM_COST_CURRENCY"


@dataclass(frozen=True, slots=True)
class TokenRates:
    """What one million input and output tokens cost, in ``currency``.

    The cache rates are optional. Unset, cache reads and writes are priced as ordinary
    input -- the pre-breakdown behaviour, so old rows and unconfigured runs are unchanged.
    """

    input_per_mtok: float
    output_per_mtok: float
    currency: str = "USD"
    cached_input_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None

    def input_cost_of(
        self, input_tokens: int, *, cached_tokens: int = 0, cache_write_tokens: int = 0
    ) -> float:
        cached = min(cached_tokens, input_tokens)
        written = min(cache_write_tokens, input_tokens - cached)
        plain = input_tokens - cached - written
        cached_rate = (
            self.input_per_mtok
            if self.cached_input_per_mtok is None
            else (self.cached_input_per_mtok)
        )
        write_rate = (
            self.input_per_mtok
            if self.cache_write_per_mtok is None
            else (self.cache_write_per_mtok)
        )
        return (
            plain * self.input_per_mtok + cached * cached_rate + written * write_rate
        ) / TOKENS_PER_MILLION

    def cost_of(self, *, input_tokens: int, output_tokens: int) -> float:
        return (
            self.input_cost_of(input_tokens)
            + output_tokens * self.output_per_mtok / TOKENS_PER_MILLION
        )


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
    # Database file size on disk, measured either side of the run. Bytes rather than row
    # counts because the question this answers is "how fast is my disk filling up", and
    # page/index overhead is part of that answer. Defaulted so ledger lines written before
    # descriptions were stored still load.
    db_bytes_before: int = 0
    db_bytes_total: int = 0
    discarded_reason: str | None = None
    unknown_usage: bool = False
    request_id: str | None = None
    # Subsets of input_tokens/output_tokens; zero when not reported by the provider.
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def db_bytes_added(self) -> int:
        """Growth attributable to this run.

        Clamped at zero: a `state prune` between two runs legitimately shrinks the file,
        and reporting that as negative growth in a column headed "added" reads as a bug.
        The shrink is visible in the total, which is where it belongs.
        """
        return max(0, self.db_bytes_total - self.db_bytes_before)

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
            "discarded_reason": self.discarded_reason,
            "unknown_usage": self.unknown_usage,
            "request_id": self.request_id,
            "completed_at": self.completed_at,
            "model_policy": self.model_policy,
            "prompt_version": self.prompt_version,
            "evaluated": self.evaluated,
            "cache_hits": self.cache_hits,
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "currency": self.currency,
            "input_cost": _rounded(self.input_cost),
            "output_cost": _rounded(self.output_cost),
            "total_cost": _rounded(self.total_cost),
            "cost_per_evaluated_job": _rounded(self.per_evaluated_job, digits=6),
            "db_bytes_before": self.db_bytes_before,
            "db_bytes_total": self.db_bytes_total,
            # Derived on write like cost_per_evaluated_job, for anyone reading the JSONL
            # directly. read_ledger recomputes it rather than trusting the stored value.
            "db_bytes_added": self.db_bytes_added,
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
    raw_cached = (values.get(CACHED_INPUT_RATE_VARIABLE) or "").strip()
    raw_write = (values.get(CACHE_WRITE_RATE_VARIABLE) or "").strip()
    return TokenRates(
        input_per_mtok=_rate(raw_input, INPUT_RATE_VARIABLE),
        output_per_mtok=_rate(raw_output, OUTPUT_RATE_VARIABLE),
        currency=(values.get(CURRENCY_VARIABLE) or "USD").strip() or "USD",
        cached_input_per_mtok=_rate(raw_cached, CACHED_INPUT_RATE_VARIABLE) if raw_cached else None,
        cache_write_per_mtok=_rate(raw_write, CACHE_WRITE_RATE_VARIABLE) if raw_write else None,
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
    db_bytes_before: int = 0,
    db_bytes_total: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> RunCost:
    """Attach cost to one run's measured usage, leaving it unpriced if rates are absent."""
    input_cost = (
        None
        if rates is None
        else rates.input_cost_of(
            input_tokens, cached_tokens=cached_input_tokens, cache_write_tokens=cache_write_tokens
        )
    )
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
        db_bytes_before=db_bytes_before,
        db_bytes_total=db_bytes_total,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def format_bytes(count: int) -> str:
    """Render a byte count at human scale. Raw byte counts do not read as sizes."""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # pragma: no cover - unreachable, the loop exits at GB


def format_cost_line(cost: RunCost) -> str:
    """One terminal line summarising what the run spent."""
    # Size is appended in both branches: it is measured from the file on disk and is
    # known whether or not token rates happen to be configured.
    disk = f" db={format_bytes(cost.db_bytes_total)} (+{format_bytes(cost.db_bytes_added)})"
    if not cost.priced:
        return (
            f"llm_cost=unavailable tokens_in={cost.input_tokens} "
            f"tokens_out={cost.output_tokens} requests={cost.request_count}{disk} "
            f"(set {INPUT_RATE_VARIABLE} and {OUTPUT_RATE_VARIABLE} to price runs)"
        )
    per_job = cost.per_evaluated_job
    suffix = "" if per_job is None else f" per_job={cost.currency} {per_job:.4f}"
    return (
        f"llm_cost={cost.currency} {cost.total_cost:.2f} "
        f"evaluated={cost.evaluated} cached={cost.cache_hits} "
        f"tokens_in={cost.input_tokens} tokens_out={cost.output_tokens}{suffix}{disk}"
    )


def summarise(history: list[RunCost]) -> dict[str, object]:
    """Aggregate a run history into the totals a daily-cost view needs.

    Unpriced runs are counted but excluded from the money totals, and reported separately,
    so a partially-configured history cannot quietly understate the spend.
    """
    priced = [item for item in history if item.priced and item.total_cost is not None]
    total = sum(item.total_cost or 0.0 for item in priced)
    evaluated = sum(item.evaluated for item in priced)
    days = {iso_day(item.completed_at) for item in priced if item.completed_at}
    single_currency = len({item.currency for item in history}) <= 1
    return {
        "runs": sum(item.request_id is None for item in history)
        + len({item.run_id for item in history if item.request_id is not None}),
        "priced_runs": len(priced),
        "unpriced_runs": len(history) - len(priced),
        "currency": priced[0].currency
        if len({item.currency for item in priced}) <= 1 and priced
        else ("mixed" if priced else "USD"),
        "total_cost": _rounded(total) if len({item.currency for item in priced}) <= 1 else None,
        "total_evaluated": evaluated,
        "mean_cost_per_run": _rounded(total / len(priced)) if priced and single_currency else None,
        "mean_cost_per_day": _rounded(total / len(days)) if days and single_currency else None,
        "cost_per_evaluated_job": _rounded(total / evaluated, digits=6)
        if evaluated and single_currency
        else None,
        "distinct_days": len(days),
        # A naive x30 of the mean day would overstate the recurring bill: a first run
        # evaluates the whole backlog, later ones only new postings. Reported so the
        # caller can decide, rather than presenting one number as "your monthly cost".
        "projected_30_day": _rounded(total / len(days) * 30) if days and single_currency else None,
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
        value = datetime.fromisoformat(timestamp)
        if value.tzinfo is not None:
            value = value.astimezone(timezone(timedelta(hours=5, minutes=30)))
        return value.date().isoformat()
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
    """Read legacy runs and typed usage events; markers never become fictitious runs."""
    if not path.exists():
        return []
    history: list[tuple[str | None, RunCost]] = []
    discarded: dict[str, str] = {}
    seen: set[str] = set()
    for line in path.read_text("utf-8").splitlines():
        try:
            raw = json.loads(line)
            if not isinstance(raw, dict):
                continue
            event_id = raw.get("event_id")
            if isinstance(event_id, str):
                if event_id in seen:
                    continue
                seen.add(event_id)
            kind = raw.get("event_type")
            if kind == "discard":
                discarded[str(raw["request_id"])] = str(raw["reason"])
                continue
            if kind not in {None, "usage"} or not raw.get("run_id"):
                continue
            item = RunCost(
                run_id=str(raw["run_id"]),
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
                db_bytes_before=int(raw.get("db_bytes_before") or 0),
                db_bytes_total=int(raw.get("db_bytes_total") or 0),
                discarded_reason=raw.get("discarded_reason"),
                unknown_usage=bool(raw.get("unknown_usage", False)),
                request_id=raw.get("request_id"),
                cached_input_tokens=int(raw.get("cached_input_tokens") or 0),
                cache_write_tokens=int(raw.get("cache_write_tokens") or 0),
                reasoning_tokens=int(raw.get("reasoning_tokens") or 0),
            )
            history.append((raw.get("request_id"), item))
        except (ValueError, TypeError, KeyError):
            _LOGGER.warning("cost_ledger_line_unreadable path=%s", path)
    return [
        replace(item, discarded_reason=discarded.get(request_id or "", item.discarded_reason))
        for request_id, item in history
    ]


def daily_totals(history: list[RunCost]) -> list[dict[str, object]]:
    """Bucket actual spending dates in IST, grouping currencies without conversion."""
    days: dict[tuple[str, str], dict[str, object]] = {}
    run_ids: dict[tuple[str, str], set[str]] = {}
    legacy_runs: dict[tuple[str, str], int] = {}
    for item in history:
        key = iso_day(item.completed_at), item.currency
        day = days.setdefault(
            key,
            {
                "day": key[0],
                "currency": key[1],
                "runs": 0,
                "evaluated": 0,
                "requests": 0,
                "cost": 0.0,
                "discarded_cost": 0.0,
                "discarded_requests": 0,
                "unknown_requests": 0,
                "unknown_usage_requests": 0,
                "bytes_added": 0,
                "bytes_total": 0,
            },
        )
        if item.request_id is None:
            legacy_runs[key] = legacy_runs.get(key, 0) + 1
        else:
            run_ids.setdefault(key, set()).add(item.run_id)
        day["runs"] = legacy_runs.get(key, 0) + len(run_ids.get(key, set()))
        for field, value in (
            ("evaluated", item.evaluated),
            ("requests", item.request_count),
            ("bytes_added", item.db_bytes_added),
        ):
            day[field] = int(day[field]) + value  # type: ignore[call-overload]
        day["cost"] = float(day["cost"]) + (item.total_cost or 0.0)  # type: ignore[arg-type]
        if not item.priced:
            day["unknown_requests"] = int(day["unknown_requests"]) + item.request_count  # type: ignore[call-overload]
        if item.unknown_usage:
            day["unknown_usage_requests"] = int(day["unknown_usage_requests"]) + item.request_count  # type: ignore[call-overload]
        if item.discarded_reason:
            day["discarded_cost"] = float(day["discarded_cost"]) + (item.total_cost or 0.0)  # type: ignore[arg-type]
            day["discarded_requests"] = int(day["discarded_requests"]) + item.request_count  # type: ignore[call-overload]
        day["bytes_total"] = item.db_bytes_total
    for day in days.values():
        day["cost"] = round(float(day["cost"]), 4)  # type: ignore[arg-type]
        day["discarded_cost"] = round(float(day["discarded_cost"]), 4)  # type: ignore[arg-type]
    return [days[key] for key in sorted(days)]


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
