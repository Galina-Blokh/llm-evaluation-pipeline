from __future__ import annotations

from eval_pipeline.metrics.composite import compute_composite, is_critical_failure
from eval_pipeline.metrics.deterministic import score_all_deterministic
from eval_pipeline.models import (
    CostSummary,
    EvalRecord,
    PipelineHealth,
    RowResult,
)
from eval_pipeline.report import build_report, write_report
from eval_pipeline.schema import validate_report_markdown, validate_results_file


def _minimal_row(record_id: str = "T-001", critical: bool = False) -> RowResult:
    rec = EvalRecord(
        id=record_id,
        query="What port?",
        context="HTTPS uses 443.",
        response="Port 443.",
        ground_truth="443",
        query_type="factual",
        difficulty="easy",
        gt_status="partial_gt",
        source_line=1,
    )
    metrics = score_all_deterministic(rec)
    composite = compute_composite(rec, metrics, judge=None, deterministic_only=True)
    return RowResult(
        record=rec,
        metrics=metrics,
        judge=None,
        composite=composite,
        critical_failure=critical or is_critical_failure(metrics, None),
    )


def test_build_report_aggregates(tmp_path):
    rows = [_minimal_row("A"), _minimal_row("B")]
    health = PipelineHealth(
        rows_total=2,
        rows_evaluated=2,
        rows_skipped=0,
        judge_provider="deterministic_only",
        degraded_mode="deterministic_only",
        cost=CostSummary(),
    )
    report = build_report(rows, health, "test.jsonl", version="0.1.0")
    assert report.aggregates["by_query_type"]["factual"]["composite_mean"] is not None
    assert report.aggregates["gt_status_counts"]["partial_gt"] == 2

    write_report(report, tmp_path)
    validate_results_file(tmp_path / "results.json")
    validate_report_markdown((tmp_path / "report.md").read_text(encoding="utf-8"))


def test_write_report_includes_critical_failure(tmp_path):
    rec = EvalRecord(
        id="A-E-003",
        query="concerned about workstation?",
        context="standard end-user workstation",
        response="should be immediately isolated",
        ground_truth="normal workstation",
        query_type="analytical",
        difficulty="easy",
        gt_status="valid",
        source_line=2,
    )
    metrics = score_all_deterministic(rec)
    row = RowResult(
        record=rec,
        metrics=metrics,
        judge=None,
        composite=compute_composite(rec, metrics, None, deterministic_only=True),
        critical_failure=is_critical_failure(metrics, None),
    )
    health = PipelineHealth(
        rows_total=1,
        rows_evaluated=1,
        rows_skipped=0,
        judge_provider="deterministic_only",
        degraded_mode="deterministic_only",
        cost=CostSummary(),
    )
    report = build_report([row], health, "test.jsonl")
    assert len(report.critical_failures) == 1
    assert report.critical_failures[0]["id"] == "A-E-003"
    write_report(report, tmp_path)
    payload = validate_results_file(tmp_path / "results.json")
    assert payload.rows[0].critical_failure is True
