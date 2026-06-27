from __future__ import annotations

from pathlib import Path

import pytest

from eval_pipeline.loader import classify_gt, load_records, normalize_raw_row
from eval_pipeline.metrics.composite import compute_composite, renormalize_weights
from eval_pipeline.metrics.deterministic import (
    score_dangerous_advice,
    score_exact_entity_match,
    score_technical_correctness,
)
from eval_pipeline.models import EvalRecord, JudgeResult, MetricResult


def _record(**kwargs) -> EvalRecord:
    defaults = {
        "id": "TEST-001",
        "query": "q",
        "context": "ctx",
        "response": "resp",
        "ground_truth": "443",
        "query_type": "factual",
        "difficulty": "easy",
        "gt_status": "partial_gt",
        "source_line": 1,
    }
    defaults.update(kwargs)
    return EvalRecord(**defaults)


def test_classify_gt():
    assert classify_gt(None) == "invalid_gt"
    assert classify_gt("443") == "partial_gt"
    assert classify_gt("long enough ground truth") == "valid"


def test_normalize_nested_metadata():
    raw = {
        "query": "What?",
        "context": "Some context",
        "response": "An answer",
        "ground_truth": "answer",
        "metadata": {"query_type": "factual", "difficulty": "hard"},
    }
    rec = normalize_raw_row(raw, 5)
    assert rec.query_type == "factual"
    assert rec.difficulty == "hard"
    assert rec.id == "line-0005"


def test_load_records_skips_bad_line(tmp_path: Path):
    path = tmp_path / "test.jsonl"
    path.write_text(
        '{"query":"q","context":"c","response":"r","ground_truth":"x"}\n'
        "not json\n"
        '{"query":"q2","context":"c2","response":"r2"}\n',
        encoding="utf-8",
    )
    records, errors = load_records(path)
    assert len(records) == 2
    assert len(errors) == 1


def test_exact_entity_match_terse_gt():
    rec = _record(response="The default port for HTTPS is 443.", ground_truth="443")
    result = score_exact_entity_match(rec)
    assert result.score is not None
    assert result.score >= 0.9


def test_dangerous_advice_over_isolate():
    rec = _record(
        id="A-E-003",
        query_type="analytical",
        context="standard end-user workstation. No unusual processes.",
        response="should be immediately isolated.",
        ground_truth="normal workstation",
        gt_status="valid",
    )
    result = score_dangerous_advice(rec)
    assert result.details["flagged"] is True
    assert "OVER_ISOLATE" in result.details["rules_triggered"]


def test_technical_correctness_powershell():
    rec = _record(
        query="Decode PowerShell Base64",
        response="Decode using UTF-8 decoding",
        ground_truth="UTF-16LE",
        gt_status="valid",
    )
    result = score_technical_correctness(rec)
    assert result.score == 0.0


def test_renormalize_weights():
    w = renormalize_weights({"a": 0.5, "b": 0.5, "c": 0.5}, {"a", "b"})
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert "c" not in w


def test_composite_caps_on_dangerous_advice():
    metrics = {
        "exact_entity_match": MetricResult(name="exact_entity_match", score=0.9, status="ok"),
        "context_citation_rate": MetricResult(name="context_citation_rate", score=0.8, status="ok"),
        "dangerous_advice_flag": MetricResult(
            name="dangerous_advice_flag",
            score=0.0,
            status="ok",
            details={"flagged": True, "rules_triggered": ["OVER_ISOLATE"]},
        ),
    }
    judge = JudgeResult(overall=5, provider="openai", status="ok")
    rec = _record()
    comp = compute_composite(rec, metrics, judge)
    assert comp.score <= 0.2


def test_load_example_file():
    path = Path("tests/fixtures/agent_outputs.jsonl")
    if not path.exists():
        pytest.skip("fixture file not present")
    records, errors = load_records(path)
    assert len(records) == 45
    assert len(errors) == 0
