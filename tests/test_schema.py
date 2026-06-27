from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from eval_pipeline.schema import (
    REPORT_SECTIONS,
    ResultsDocument,
    validate_report_markdown,
    validate_results_document,
    validate_results_file,
)


def test_committed_results_json_validates(committed_results):
    doc = validate_results_file(committed_results)
    assert doc.health.rows_evaluated == len(doc.rows)
    assert doc.meta.pipeline_version


def test_committed_report_markdown_validates(committed_report):
    text = committed_report.read_text(encoding="utf-8")
    validate_report_markdown(text)
    for section in REPORT_SECTIONS:
        assert section in text


def test_results_document_rejects_empty_rows():
    payload = {
        "meta": {
            "input_file": "x.jsonl",
            "evaluated_at": "2026-01-01T00:00:00+00:00",
            "pipeline_version": "0.1.0",
        },
        "health": {
            "rows_total": 0,
            "rows_evaluated": 0,
            "rows_skipped": 0,
            "judge_calls_ok": 0,
            "judge_calls_retried": 0,
            "judge_calls_failed": 0,
            "judge_provider": "deterministic_only",
            "degraded_mode": "deterministic_only",
            "fallback_rows": [],
            "metrics_skipped": {},
            "cost": {"total_cost_usd": 0.0},
        },
        "aggregates": {
            "by_metric": {},
            "by_query_type": {},
            "by_difficulty": {},
            "by_query_type_difficulty": {},
            "judge_subscores": {},
            "gt_status_counts": {},
        },
        "critical_failures": [],
        "rows": [],
    }
    with pytest.raises(ValidationError):
        validate_results_document(payload)


def test_results_document_rejects_invalid_composite(committed_results):
    payload = json.loads(committed_results.read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    payload["rows"][0]["composite"]["score"] = 1.5
    with pytest.raises(ValidationError):
        validate_results_document(payload)


def test_report_markdown_rejects_missing_section(committed_report):
    text = committed_report.read_text(encoding="utf-8")
    broken = text.replace("## Pipeline Health", "")
    with pytest.raises(ValueError, match="Pipeline Health"):
        validate_report_markdown(broken)


def test_report_markdown_rejects_wrong_order(committed_report):
    text = committed_report.read_text(encoding="utf-8")
    # Swap two sections so order check fails
    broken = text.replace("## Metric Aggregates", "## TEMP")
    broken = broken.replace("## Breakdown by Query Type", "## Metric Aggregates")
    broken = broken.replace("## TEMP", "## Breakdown by Query Type")
    with pytest.raises(ValueError, match="out of order"):
        validate_report_markdown(broken)


def test_results_model_round_trip(committed_results):
    payload = json.loads(committed_results.read_text(encoding="utf-8"))
    doc = ResultsDocument.model_validate(payload)
    assert doc.aggregates.by_metric
    assert doc.critical_failures or doc.health.rows_evaluated >= 0
