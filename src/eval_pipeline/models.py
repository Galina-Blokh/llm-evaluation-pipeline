from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MetricStatus = Literal["ok", "skipped", "fallback", "failed"]
GtStatus = Literal["valid", "partial_gt", "invalid_gt"]
JudgeProvider = Literal["openai", "groq", "deterministic_only"]
JudgeStatus = Literal["ok", "retried", "fallback_deterministic", "skipped"]
CompositeStatus = Literal["full", "partial", "deterministic_only"]
DegradedMode = Literal["false", "partial", "deterministic_only"]


class EvalRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    query: str
    context: str
    response: str
    ground_truth: str | None = None
    query_type: str | None = None
    difficulty: str | None = None
    gt_status: GtStatus
    source_line: int


class IngestError(BaseModel):
    source_line: int
    message: str
    raw_snippet: str | None = None


class MetricResult(BaseModel):
    name: str
    score: float | None = None
    status: MetricStatus = "ok"
    details: dict[str, Any] = Field(default_factory=dict)


class JudgeResult(BaseModel):
    groundedness: int = 1
    safety: int = 1
    procedure: int = 1
    context_use: int = 1
    overall: int = 1
    reasoning: str = ""
    flags: list[str] = Field(default_factory=list)
    provider: JudgeProvider = "deterministic_only"
    status: JudgeStatus = "ok"
    input_tokens: int = 0
    output_tokens: int = 0


class CompositeResult(BaseModel):
    score: float
    status: CompositeStatus
    weights_applied: dict[str, float] = Field(default_factory=dict)


class RowResult(BaseModel):
    record: EvalRecord
    metrics: dict[str, MetricResult]
    judge: JudgeResult | None = None
    composite: CompositeResult
    critical_failure: bool = False


class CostSummary(BaseModel):
    openai_input_tokens: int = 0
    openai_output_tokens: int = 0
    openai_cost_usd: float = 0.0
    groq_input_tokens: int = 0
    groq_output_tokens: int = 0
    groq_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


class PipelineHealth(BaseModel):
    rows_total: int
    rows_evaluated: int
    rows_skipped: int
    judge_calls_ok: int = 0
    judge_calls_retried: int = 0
    judge_calls_failed: int = 0
    judge_provider: JudgeProvider = "deterministic_only"
    degraded_mode: DegradedMode = "false"
    fallback_rows: list[str] = Field(default_factory=list)
    metrics_skipped: dict[str, int] = Field(default_factory=dict)
    cost: CostSummary = Field(default_factory=CostSummary)


class ReportData(BaseModel):
    meta: dict[str, Any]
    health: PipelineHealth
    aggregates: dict[str, Any]
    critical_failures: list[dict[str, Any]]
    rows: list[RowResult]
