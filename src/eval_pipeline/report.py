from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from eval_pipeline.models import PipelineHealth, ReportData, RowResult
from eval_pipeline.schema import validate_report_markdown, validate_results_document


def _mean_std(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "std": None}
    if len(values) == 1:
        return {"mean": round(values[0], 4), "std": 0.0}
    return {"mean": round(statistics.mean(values), 4), "std": round(statistics.pstdev(values), 4)}


def build_report(
    rows: list[RowResult],
    health: PipelineHealth,
    input_file: str,
    version: str = "0.1.0",
) -> ReportData:
    aggregates: dict = {
        "by_metric": {},
        "by_query_type": {},
        "by_difficulty": {},
        "by_query_type_difficulty": {},
        "judge_subscores": {},
        "gt_status_counts": defaultdict(int),
    }

    metric_values: dict[str, list[float]] = defaultdict(list)
    composite_by_type: dict[str, list[float]] = defaultdict(list)
    composite_by_diff: dict[str, list[float]] = defaultdict(list)
    composite_cross: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    judge_dims: dict[str, list[int]] = defaultdict(list)

    critical_failures: list[dict] = []

    for row in rows:
        aggregates["gt_status_counts"][row.record.gt_status] += 1
        qtype = row.record.query_type or "unknown"
        diff = row.record.difficulty or "unknown"
        composite_by_type[qtype].append(row.composite.score)
        composite_by_diff[diff].append(row.composite.score)
        composite_cross[qtype][diff].append(row.composite.score)

        for name, metric in row.metrics.items():
            if metric.score is not None and metric.status == "ok":
                metric_values[name].append(metric.score)

        if row.judge and row.judge.status in ("ok", "retried"):
            judge_dims["groundedness"].append(row.judge.groundedness)
            judge_dims["safety"].append(row.judge.safety)
            judge_dims["procedure"].append(row.judge.procedure)
            judge_dims["context_use"].append(row.judge.context_use)

        if row.critical_failure:
            danger = row.metrics.get("dangerous_advice_flag")
            critical_failures.append(
                {
                    "id": row.record.id,
                    "query_snippet": row.record.query[:80],
                    "composite": row.composite.score,
                    "judge_overall": row.judge.overall if row.judge else None,
                    "flags": row.judge.flags if row.judge else [],
                    "rules_triggered": danger.details.get("rules_triggered", []) if danger else [],
                }
            )

    for name, vals in metric_values.items():
        aggregates["by_metric"][name] = _mean_std(vals)

    for qtype, vals in composite_by_type.items():
        aggregates["by_query_type"][qtype] = {"composite_mean": _mean_std(vals)["mean"]}

    for diff, vals in composite_by_diff.items():
        aggregates["by_difficulty"][diff] = {"composite_mean": _mean_std(vals)["mean"]}

    for qtype, diffs in composite_cross.items():
        aggregates["by_query_type_difficulty"][qtype] = {
            d: {"composite_mean": _mean_std(v)["mean"]} for d, v in diffs.items()
        }

    for dim, vals in judge_dims.items():
        aggregates["judge_subscores"][dim] = round(statistics.mean(vals), 2) if vals else None

    aggregates["gt_status_counts"] = dict(aggregates["gt_status_counts"])

    meta = {
        "input_file": input_file,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "pipeline_version": version,
    }

    return ReportData(
        meta=meta,
        health=health,
        aggregates=aggregates,
        critical_failures=critical_failures,
        rows=rows,
    )


def _row_to_json(row: RowResult) -> dict:
    metrics = {
        k: {"score": v.score, "status": v.status, "details": v.details}
        for k, v in row.metrics.items()
    }
    judge = None
    if row.judge:
        judge = {
            "overall": row.judge.overall,
            "groundedness": row.judge.groundedness,
            "safety": row.judge.safety,
            "procedure": row.judge.procedure,
            "context_use": row.judge.context_use,
            "provider": row.judge.provider,
            "status": row.judge.status,
            "reasoning": row.judge.reasoning,
            "flags": row.judge.flags,
        }
    return {
        "id": row.record.id,
        "query_type": row.record.query_type,
        "difficulty": row.record.difficulty,
        "gt_status": row.record.gt_status,
        "metrics": metrics,
        "judge": judge,
        "composite": {"score": row.composite.score, "status": row.composite.status},
        "critical_failure": row.critical_failure,
    }


def write_report(data: ReportData, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    results_payload = {
        "meta": data.meta,
        "health": data.health.model_dump(),
        "aggregates": data.aggregates,
        "critical_failures": data.critical_failures,
        "rows": [_row_to_json(r) for r in data.rows],
    }
    validate_results_document(results_payload)

    md = _render_markdown(data)
    validate_report_markdown(md)

    (output_dir / "results.json").write_text(
        json.dumps(results_payload, indent=2), encoding="utf-8"
    )
    (output_dir / "report.md").write_text(md, encoding="utf-8")


def _render_markdown(data: ReportData) -> str:
    h = data.health
    cost = h.cost
    lines = [
        "# Evaluation Report",
        "",
        "## Executive Summary",
        f"- Records evaluated: **{h.rows_evaluated}** / {h.rows_total}",
        f"- Critical failures: **{len(data.critical_failures)}**",
        f"- Degraded mode: **{h.degraded_mode}**",
        f"- Total API cost: **${cost.total_cost_usd:.4f}**",
        "",
        "## Metric Aggregates",
    ]
    for name, stats in data.aggregates.get("by_metric", {}).items():
        lines.append(f"- **{name}**: mean={stats.get('mean')}, std={stats.get('std')}")
    lines.extend(["", "## Breakdown by Query Type"])
    for qtype, stats in data.aggregates.get("by_query_type", {}).items():
        lines.append(f"- **{qtype}**: composite mean={stats.get('composite_mean')}")
    lines.extend(["", "## Breakdown by Difficulty"])
    for diff, stats in data.aggregates.get("by_difficulty", {}).items():
        lines.append(f"- **{diff}**: composite mean={stats.get('composite_mean')}")
    lines.extend(["", "## Cross-tab: Query Type × Difficulty"])
    for qtype, diffs in data.aggregates.get("by_query_type_difficulty", {}).items():
        for diff, stats in diffs.items():
            lines.append(f"- **{qtype} / {diff}**: composite mean={stats.get('composite_mean')}")
    lines.extend(["", "## Judge Sub-score Analysis"])
    for dim, val in data.aggregates.get("judge_subscores", {}).items():
        lines.append(f"- **{dim}**: {val}")
    lines.extend(["", "## Critical Failures"])
    if not data.critical_failures:
        lines.append("- None")
    else:
        for cf in data.critical_failures:
            lines.append(
                f"- **{cf['id']}** (composite={cf['composite']}, judge={cf['judge_overall']}): "
                f"{cf['query_snippet']}… flags={cf['flags']} rules={cf['rules_triggered']}"
            )
    lines.extend(["", "## Ground Truth Handling"])
    for status, count in data.aggregates.get("gt_status_counts", {}).items():
        lines.append(f"- **{status}**: {count}")
    lines.extend(
        [
            "",
            "## Pipeline Health",
            f"- Judge provider: {h.judge_provider}",
            (
                f"- Judge OK / retried / failed: {h.judge_calls_ok} / "
                f"{h.judge_calls_retried} / {h.judge_calls_failed}"
            ),
            f"- Fallback rows: {', '.join(h.fallback_rows) if h.fallback_rows else 'none'}",
            "",
            "## API Cost Estimate",
            (
                f"- OpenAI: {cost.openai_input_tokens} in + {cost.openai_output_tokens} out "
                f"= ${cost.openai_cost_usd:.6f}"
            ),
            (
                f"- Groq: {cost.groq_input_tokens} in + {cost.groq_output_tokens} out "
                f"= ${cost.groq_cost_usd:.6f}"
            ),
            f"- **Total: ${cost.total_cost_usd:.6f}**",
            "",
            "## Chart",
            "![Agent Quality by Query Type and Difficulty](chart.png)",
            "",
        ]
    )
    return "\n".join(lines)
