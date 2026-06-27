"""Pydantic schemas for pipeline output validation (spec §8)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

REPORT_SECTIONS: tuple[str, ...] = (
    "## Executive Summary",
    "## Metric Aggregates",
    "## Breakdown by Query Type",
    "## Breakdown by Difficulty",
    "## Cross-tab: Query Type × Difficulty",
    "## Judge Sub-score Analysis",
    "## Critical Failures",
    "## Ground Truth Handling",
    "## Pipeline Health",
    "## API Cost Estimate",
    "## Chart",
)


class MetricStats(BaseModel):
    mean: float | None
    std: float | None


class CompositeMean(BaseModel):
    composite_mean: float | None


class CostDoc(BaseModel):
    openai_input_tokens: int = 0
    openai_output_tokens: int = 0
    openai_cost_usd: float = 0.0
    groq_input_tokens: int = 0
    groq_output_tokens: int = 0
    groq_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


class HealthDoc(BaseModel):
    rows_total: int = Field(ge=0)
    rows_evaluated: int = Field(ge=0)
    rows_skipped: int = Field(ge=0)
    judge_calls_ok: int = Field(ge=0)
    judge_calls_retried: int = Field(ge=0)
    judge_calls_failed: int = Field(ge=0)
    judge_provider: str
    degraded_mode: str
    fallback_rows: list[str]
    metrics_skipped: dict[str, int]
    cost: CostDoc


class MetaDoc(BaseModel):
    input_file: str
    evaluated_at: str
    pipeline_version: str


class CriticalFailureDoc(BaseModel):
    id: str
    query_snippet: str
    composite: float
    judge_overall: int | None = None
    flags: list[str]
    rules_triggered: list[str]


class RowMetricDoc(BaseModel):
    score: float | None = None
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class RowJudgeDoc(BaseModel):
    overall: int = Field(ge=1, le=5)
    groundedness: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    procedure: int = Field(ge=1, le=5)
    context_use: int = Field(ge=1, le=5)
    provider: str
    status: str
    reasoning: str = ""
    flags: list[str] = Field(default_factory=list)


class RowCompositeDoc(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    status: str


class RowDoc(BaseModel):
    id: str
    query_type: str | None = None
    difficulty: str | None = None
    gt_status: str
    metrics: dict[str, RowMetricDoc]
    judge: RowJudgeDoc | None = None
    composite: RowCompositeDoc
    critical_failure: bool


class AggregatesDoc(BaseModel):
    by_metric: dict[str, MetricStats]
    by_query_type: dict[str, CompositeMean]
    by_difficulty: dict[str, CompositeMean]
    by_query_type_difficulty: dict[str, dict[str, CompositeMean]]
    judge_subscores: dict[str, float | None]
    gt_status_counts: dict[str, int]

    @field_validator("gt_status_counts")
    @classmethod
    def _non_negative_counts(cls, v: dict[str, int]) -> dict[str, int]:
        for count in v.values():
            if count < 0:
                raise ValueError("gt_status_counts must be non-negative")
        return v


class ResultsDocument(BaseModel):
    meta: MetaDoc
    health: HealthDoc
    aggregates: AggregatesDoc
    critical_failures: list[CriticalFailureDoc]
    rows: list[RowDoc]

    @field_validator("rows")
    @classmethod
    def _rows_non_empty(cls, v: list[RowDoc]) -> list[RowDoc]:
        if not v:
            raise ValueError("results.json must contain at least one row")
        return v


def validate_results_document(data: dict[str, Any]) -> ResultsDocument:
    """Validate a results.json payload; raises ValidationError on mismatch."""
    return ResultsDocument.model_validate(data)


def validate_results_file(path: str | Any) -> ResultsDocument:
    """Load and validate results.json from disk."""
    import json
    from pathlib import Path

    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    return validate_results_document(payload)


def validate_report_markdown(text: str) -> None:
    """Ensure report.md contains all required sections in order (spec §8.2)."""
    if not text.startswith("# Evaluation Report"):
        raise ValueError("report.md must start with '# Evaluation Report'")

    positions: list[int] = []
    for section in REPORT_SECTIONS:
        idx = text.find(section)
        if idx < 0:
            raise ValueError(f"report.md missing required section: {section!r}")
        positions.append(idx)

    if positions != sorted(positions):
        raise ValueError("report.md sections are out of order")

    if "chart.png" not in text:
        raise ValueError("report.md must reference chart.png")

    if not re.search(r"!\[.*\]\(chart\.png\)", text):
        raise ValueError("report.md must include chart.png markdown image")
