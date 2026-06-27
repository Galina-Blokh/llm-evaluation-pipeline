from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from pathlib import Path

from eval_pipeline import __version__
from eval_pipeline.config import Settings
from eval_pipeline.cost_tracker import CostTracker
from eval_pipeline.judge.client import JudgeStats, judge_batch
from eval_pipeline.loader import load_records
from eval_pipeline.metrics.composite import compute_composite, is_critical_failure
from eval_pipeline.metrics.deterministic import score_all_deterministic, score_token_f1
from eval_pipeline.models import DegradedMode, PipelineHealth, RowResult
from eval_pipeline.report import build_report, write_report
from eval_pipeline.visualize import render_chart

CALIBRATION_IDS = [
    "F-E-001",
    "F-E-004",
    "A-E-003",
    "P-E-002",
    "A-H-002",
    "P-M-004",
    "P-M-005",
    "P-H-003",
]

CALIBRATION_EXPECTED: dict[str, tuple[float | None, float | None]] = {
    "F-E-001": (4, None),
    "F-E-004": (None, 2),
    "A-E-003": (None, 2),
    "P-E-002": (None, 2),
    "A-H-002": (3, 4),
    "P-M-004": (None, 2),
    "P-M-005": (None, 2),
    "P-H-003": (None, 2),
}


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM evaluation pipeline")
    parser.add_argument("--input", type=Path, default=Path("agent_outputs.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--max-judge-calls", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _check_calibration(rows: list[RowResult]) -> bool:
    passed = 0
    for row in rows:
        rid = row.record.id
        if rid not in CALIBRATION_EXPECTED or not row.judge:
            continue
        lo, hi = CALIBRATION_EXPECTED[rid]
        score = row.judge.overall
        ok = True
        if lo is not None and score < lo:
            ok = False
        if hi is not None and score > hi:
            ok = False
        if ok:
            passed += 1
        logging.getLogger(__name__).info(
            "Calibration %s: overall=%d expected [%s,%s] -> %s",
            rid,
            score,
            lo,
            hi,
            "PASS" if ok else "FAIL",
        )
    total = len(CALIBRATION_EXPECTED)
    logging.getLogger(__name__).info("Calibration: %d/%d passed", passed, total)
    return passed >= 7


async def run_pipeline(args: argparse.Namespace) -> int:
    logger = logging.getLogger(__name__)
    settings = Settings()
    if args.concurrency is not None:
        settings.max_concurrency = args.concurrency
    if args.max_judge_calls is not None:
        settings.max_judge_calls = args.max_judge_calls

    try:
        records, ingest_errors = load_records(args.input)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 3

    if args.calibrate:
        records = [r for r in records if r.id in CALIBRATION_IDS]

    if not records:
        logger.error("No evaluable records")
        return 3

    skip_judge = args.skip_judge or (not settings.has_openai() and not settings.has_groq())
    if skip_judge and not args.skip_judge:
        logger.warning("No API keys found — running deterministic-only mode")

    cost_tracker = CostTracker(
        openai_input_cost_per_m=settings.openai_input_cost_per_m,
        openai_output_cost_per_m=settings.openai_output_cost_per_m,
        groq_input_cost_per_m=settings.groq_input_cost_per_m,
        groq_output_cost_per_m=settings.groq_output_cost_per_m,
    )
    judge_stats = JudgeStats()

    row_results: list[RowResult] = []
    metrics_skipped: dict[str, int] = defaultdict(int)

    deterministic_only = skip_judge

    # Deterministic metrics (sync)
    all_metrics = {r.id: score_all_deterministic(r) for r in records}

    # Judge (async)
    judge_results = await judge_batch(
        records,
        settings,
        cost_tracker,
        judge_stats,
        skip_judge=skip_judge,
    )

    for record in records:
        metrics = dict(all_metrics[record.id])
        judge = judge_results.get(record.id)

        if deterministic_only and record.ground_truth:
            metrics["token_f1"] = score_token_f1(record)

        composite = compute_composite(
            record,
            metrics,
            judge,
            deterministic_only=deterministic_only or judge is None,
        )
        critical = is_critical_failure(metrics, judge)

        for m in metrics.values():
            if m.status == "skipped":
                metrics_skipped[m.name] += 1

        row_results.append(
            RowResult(
                record=record,
                metrics=metrics,
                judge=judge,
                composite=composite,
                critical_failure=critical,
            )
        )

    degraded: DegradedMode = "false"
    if deterministic_only:
        degraded = "deterministic_only"
    elif judge_stats.calls_failed > 0:
        degraded = "partial"

    health = PipelineHealth(
        rows_total=len(records) + len(ingest_errors),
        rows_evaluated=len(row_results),
        rows_skipped=len(ingest_errors),
        judge_calls_ok=judge_stats.calls_ok,
        judge_calls_retried=judge_stats.calls_retried,
        judge_calls_failed=judge_stats.calls_failed,
        judge_provider=judge_stats.primary_provider,
        degraded_mode=degraded,
        fallback_rows=judge_stats.fallback_rows,
        metrics_skipped=dict(metrics_skipped),
        cost=cost_tracker.summary(),
    )

    report = build_report(row_results, health, str(args.input), version=__version__)
    write_report(report, args.output)
    render_chart(row_results, args.output / "chart.png")

    if args.calibrate:
        if not _check_calibration(row_results):
            return 1

    print(
        f"Done: {health.rows_evaluated} rows evaluated, "
        f"{len(report.critical_failures)} critical failures, "
        f"cost=${health.cost.total_cost_usd:.4f} -> {args.output}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    try:
        return asyncio.run(run_pipeline(args))
    except Exception:
        logging.getLogger(__name__).exception("Pipeline failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
