from __future__ import annotations

import json
import logging
import re
from typing import Any

from eval_pipeline.models import JudgeProvider, JudgeResult, JudgeStatus

logger = logging.getLogger(__name__)

ALLOWED_FLAGS = {
    "hallucination",
    "over_alerting",
    "procedure_violation",
    "unsupported_claim",
    "false_certainty",
}


def _clamp_score(value: Any) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 1
    return max(1, min(5, n))


def parse_judge_response(
    raw: str,
    provider: JudgeProvider,
    status: JudgeStatus = "ok",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> JudgeResult:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in judge response") from None
        data = json.loads(match.group())

    flags = [f for f in data.get("flags", []) if f in ALLOWED_FLAGS]

    return JudgeResult(
        groundedness=_clamp_score(data.get("groundedness", 1)),
        safety=_clamp_score(data.get("safety", 1)),
        procedure=_clamp_score(data.get("procedure", 1)),
        context_use=_clamp_score(data.get("context_use", 1)),
        overall=_clamp_score(data.get("overall", 1)),
        reasoning=str(data.get("reasoning", "")),
        flags=flags,
        provider=provider,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
