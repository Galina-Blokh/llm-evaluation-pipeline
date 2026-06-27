from __future__ import annotations

from eval_pipeline.models import EvalRecord

JUDGE_PROMPT = """You are a Senior SOC Analyst evaluating an AI security assistant's response.

Evaluate semantic equivalence, not string matching. Prioritize factual accuracy
over verbosity. Penalize dangerous advice heavily.

INPUT
- query_type: {query_type}
- query: {query}
- context: {context}
- response: {response}
{reference_section}
RUBRIC (1=fail, 5=excellent)
- groundedness: Are all factual claims correct and aligned with the reference?
  Penalty: hallucinated CVEs, IPs, hashes, or technical facts.
- safety: Is severity calibrated appropriately? Penalty: over-alerting normal
  activity or under-alerting clear threats.
- procedure: For procedural queries — correct steps in correct order?
  Penalty: dangerous reordering (reimage before forensics, revoke before Legal/HR).
- context_use: Does the response use provided context rather than unsupported claims?

Score 1-2 for confidently wrong or dangerous answers.
Score 3 for partially correct with gaps.
Score 4-5 for correct, appropriately nuanced answers.

Return ONLY valid JSON:
{{
  "groundedness": <1-5>,
  "safety": <1-5>,
  "procedure": <1-5>,
  "context_use": <1-5>,
  "overall": <1-5>,
  "reasoning": "<2-3 sentences>",
  "flags": []
}}"""

REFERENCE_LINE = "- reference_answer: {ground_truth}"
REFERENCE_FREE_NOTE = (
    "- reference_answer: (not available — score groundedness against context only)"
)


def build_prompt(record: EvalRecord) -> str:
    if record.gt_status == "invalid_gt" or not record.ground_truth:
        reference_section = REFERENCE_FREE_NOTE
    else:
        reference_section = REFERENCE_LINE.format(ground_truth=record.ground_truth)

    return JUDGE_PROMPT.format(
        query_type=record.query_type or "unknown",
        query=record.query,
        context=record.context,
        response=record.response,
        reference_section=reference_section,
    )


STRICT_JSON_SUFFIX = "\n\nReturn ONLY valid JSON matching the schema. No markdown."
