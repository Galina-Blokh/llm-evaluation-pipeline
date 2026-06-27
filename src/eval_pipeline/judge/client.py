from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from eval_pipeline.config import Settings
from eval_pipeline.cost_tracker import CostTracker
from eval_pipeline.judge.parser import parse_judge_response
from eval_pipeline.judge.prompt import STRICT_JSON_SUFFIX, build_prompt
from eval_pipeline.models import EvalRecord, JudgeProvider, JudgeResult

logger = logging.getLogger(__name__)


@dataclass
class JudgeStats:
    calls_ok: int = 0
    calls_retried: int = 0
    calls_failed: int = 0
    fallback_rows: list[str] = field(default_factory=list)
    primary_provider: JudgeProvider = "deterministic_only"


async def _call_openai(prompt: str, settings: Settings) -> tuple[str, int, int]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=settings.judge_temperature,
        max_tokens=settings.judge_max_tokens,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    usage = response.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    return content, in_tok, out_tok


async def _call_groq(prompt: str, settings: Settings) -> tuple[str, int, int]:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=settings.groq_api_key)
    response = await client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=settings.judge_temperature,
        max_tokens=settings.judge_max_tokens,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    usage = response.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    return content, in_tok, out_tok


async def _call_provider(
    provider: JudgeProvider, prompt: str, settings: Settings
) -> tuple[str, int, int]:
    if provider == "openai":
        return await _call_openai(prompt, settings)
    if provider == "groq":
        return await _call_groq(prompt, settings)
    raise ValueError(f"Unsupported provider: {provider}")


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in (
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
    )


async def judge_record(
    record: EvalRecord,
    settings: Settings,
    cost_tracker: CostTracker,
    stats: JudgeStats,
    *,
    prefer_groq: bool = False,
) -> JudgeResult | None:
    prompt = build_prompt(record)
    providers: list[JudgeProvider] = []
    if prefer_groq and settings.has_groq():
        providers.append("groq")
    elif settings.has_openai():
        providers.append("openai")
    if settings.has_groq() and "groq" not in providers:
        providers.append("groq")

    if not providers:
        stats.calls_failed += 1
        stats.fallback_rows.append(record.id)
        return None

    retries = [0, 2, 4, 8]
    last_exc: Exception | None = None

    for provider in providers:
        current_prompt = prompt
        for attempt, delay in enumerate(retries):
            try:
                if delay:
                    await asyncio.sleep(delay)
                    stats.calls_retried += 1
                raw, in_tok, out_tok = await _call_provider(provider, current_prompt, settings)
                cost_tracker.add(provider, in_tok, out_tok)
                status = "retried" if attempt > 0 else "ok"
                result = parse_judge_response(
                    raw, provider, status=status, input_tokens=in_tok, output_tokens=out_tok
                )
                stats.calls_ok += 1
                if stats.primary_provider == "deterministic_only":
                    stats.primary_provider = provider
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Judge call failed for %s via %s (attempt %d): %s",
                    record.id,
                    provider,
                    attempt + 1,
                    exc,
                )
                if "json" in str(exc).lower() or "JSON" in type(exc).__name__:
                    current_prompt = prompt + STRICT_JSON_SUFFIX
                    continue
                if _is_retryable(exc) and attempt < len(retries) - 1:
                    continue
                break

    logger.error("All judge providers failed for %s: %s", record.id, last_exc)
    stats.calls_failed += 1
    stats.fallback_rows.append(record.id)
    return None


async def judge_batch(
    records: list[EvalRecord],
    settings: Settings,
    cost_tracker: CostTracker,
    stats: JudgeStats,
    *,
    skip_judge: bool = False,
    prefer_groq: bool = False,
) -> dict[str, JudgeResult | None]:
    if skip_judge:
        stats.primary_provider = "deterministic_only"
        return {r.id: None for r in records}

    max_calls = settings.max_judge_calls
    to_judge = records[:max_calls] if max_calls is not None else records
    sem = asyncio.Semaphore(settings.max_concurrency)
    results: dict[str, JudgeResult | None] = {r.id: None for r in records}

    async def _run(rec: EvalRecord) -> None:
        async with sem:
            results[rec.id] = await judge_record(
                rec, settings, cost_tracker, stats, prefer_groq=prefer_groq
            )

    await asyncio.gather(*[_run(r) for r in to_judge])
    return results
