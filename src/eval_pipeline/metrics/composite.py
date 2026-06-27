from __future__ import annotations

from eval_pipeline.models import (
    CompositeResult,
    CompositeStatus,
    EvalRecord,
    JudgeResult,
    MetricResult,
)

WEIGHTS: dict[str, dict[str, float]] = {
    "factual": {
        "exact_entity_match": 0.35,
        "context_citation_rate": 0.15,
        "judge_overall": 0.50,
    },
    "analytical": {
        "exact_entity_match": 0.10,
        "context_citation_rate": 0.15,
        "severity_calibration": 0.30,
        "judge_overall": 0.45,
    },
    "procedural": {
        "exact_entity_match": 0.05,
        "context_citation_rate": 0.10,
        "procedure_step_score": 0.35,
        "judge_overall": 0.50,
    },
}

METRIC_KEYS = {
    "exact_entity_match",
    "context_citation_rate",
    "procedure_step_score",
    "severity_calibration",
    "judge_overall",
}


def renormalize_weights(weights: dict[str, float], available: set[str]) -> dict[str, float]:
    filtered = {k: v for k, v in weights.items() if k in available and v > 0}
    total = sum(filtered.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in filtered.items()}


def _default_weights(available: set[str]) -> dict[str, float]:
    n = len(available)
    if n == 0:
        return {}
    return {k: 1.0 / n for k in available}


def _get_base_weights(record: EvalRecord) -> dict[str, float]:
    qtype = record.query_type or "unknown"
    if qtype in WEIGHTS:
        return dict(WEIGHTS[qtype])
    return {}


def _normalize_judge_score(overall: int) -> float:
    return max(0.0, min(1.0, (overall - 1) / 4))


def compute_composite(
    record: EvalRecord,
    metrics: dict[str, MetricResult],
    judge: JudgeResult | None,
    *,
    deterministic_only: bool = False,
) -> CompositeResult:
    available: dict[str, float] = {}

    for key in (
        "exact_entity_match",
        "context_citation_rate",
        "procedure_step_score",
        "severity_calibration",
    ):
        m = metrics.get(key)
        if m and m.status == "ok" and m.score is not None:
            available[key] = m.score

    if judge and judge.status in ("ok", "retried") and not deterministic_only:
        available["judge_overall"] = _normalize_judge_score(judge.overall)

    base = _get_base_weights(record)
    if not base:
        base = _default_weights(set(available.keys()))

    weights = renormalize_weights(base, set(available.keys()))
    if not weights:
        return CompositeResult(score=0.0, status="deterministic_only", weights_applied={})

    score = sum(weights[k] * available[k] for k in weights)

    tech = metrics.get("technical_correctness_check")
    if tech and tech.status == "ok" and tech.score is not None and tech.score < 1.0:
        score = max(0.0, score - 0.15)

    danger = metrics.get("dangerous_advice_flag")
    if danger and danger.details.get("flagged"):
        score = min(score, 0.2)

    if deterministic_only or not judge or judge.status == "fallback_deterministic":
        comp_status: CompositeStatus = "deterministic_only" if deterministic_only else "partial"
    elif len(weights) < len(base):
        comp_status = "partial"
    else:
        comp_status = "full"

    return CompositeResult(
        score=round(max(0.0, min(1.0, score)), 4),
        status=comp_status,
        weights_applied=weights,
    )


def is_critical_failure(metrics: dict[str, MetricResult], judge: JudgeResult | None) -> bool:
    danger = metrics.get("dangerous_advice_flag")
    if danger and danger.details.get("flagged"):
        return True
    if judge and judge.overall <= 2:
        return True
    sev = metrics.get("severity_calibration")
    if sev and sev.score is not None and sev.score == 0.0:
        return True
    proc = metrics.get("procedure_step_score")
    if proc and proc.score is not None and proc.score < 0.3:
        return True
    return False
