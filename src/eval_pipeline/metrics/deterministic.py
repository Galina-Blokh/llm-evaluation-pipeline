from __future__ import annotations

import re
from typing import Literal

from eval_pipeline.models import EvalRecord, MetricResult

ENTITY_PATTERNS = {
    "ipv4": r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
    "cve": r"CVE-\d{4}-\d{4,7}",
    "mitre": r"\bT\d{4}(?:\.\d{3})?\b",
    "event_id": r"\bEventID\s+\d+\b|\bEvent ID\s+\d+\b",
    "port": r"\bport\s+\d{1,5}\b|\b:\d{1,5}\b",
    "hostname": r"\b[A-Z]{2,}-[A-Z0-9-]+\b",
    "account": r"\bsvc_[a-z0-9_]+\b|\badmin\b",
}

SEVERITY_KEYWORDS: dict[str, list[str]] = {
    "none": [
        "no concern",
        "normal",
        "not suspicious",
        "low suspicion",
        "not inherently suspicious",
    ],
    "low": ["low suspicion", "minor", "unlikely", "may warrant", "further investigation"],
    "medium": ["moderate", "suspicious", "anomalous", "investigate"],
    "high": [
        "high concern",
        "highly suspicious",
        "critical",
        "immediately isolate",
        "serious security risk",
        "significant concern",
    ],
    "inconclusive": [
        "ambiguous",
        "unclear",
        "requires additional",
        "cannot determine",
        "premature",
        "without these details",
    ],
}

SEVERITY_ORDER = ["none", "low", "medium", "high", "inconclusive"]

PROCEDURE_VERBS = [
    "isolate",
    "preserve",
    "notify",
    "reimage",
    "identify",
    "scan",
    "block",
    "retrieve",
    "restore",
    "revoke",
    "investigate",
    "forensic",
    "evidence",
    "legal",
]

SeverityLevel = Literal["none", "low", "medium", "high", "inconclusive"]


def _extract_entities(text: str, include_terse_literal: str | None = None) -> set[str]:
    entities: set[str] = set()
    for pattern in ENTITY_PATTERNS.values():
        entities.update(re.findall(pattern, text, flags=re.IGNORECASE))
    if include_terse_literal and len(include_terse_literal.strip()) <= 5:
        entities.add(include_terse_literal.strip())
    return {e.lower() for e in entities}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _classify_severity(text: str) -> SeverityLevel:
    lower = text.lower()
    counts = {
        level: sum(1 for kw in keywords if kw in lower)
        for level, keywords in SEVERITY_KEYWORDS.items()
    }
    best = max(counts.values())
    if best == 0:
        return "inconclusive"
    winners = [level for level, count in counts.items() if count == best]
    if len(winners) > 1:
        return "inconclusive"
    return winners[0]  # type: ignore[return-value]


def _severity_distance(a: SeverityLevel, b: SeverityLevel) -> int:
    try:
        return abs(SEVERITY_ORDER.index(a) - SEVERITY_ORDER.index(b))
    except ValueError:
        return 99


def _extract_procedure_steps(text: str) -> list[str]:
    steps: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\d+[\.)]\s+", line):
            steps.append(re.sub(r"^\d+[\.)]\s+", "", line).lower())
            continue
        if line.startswith(("-", "*", "•")):
            steps.append(line.lstrip("-*• ").lower())
            continue
    if steps:
        return steps

    lower = text.lower()
    found = [verb for verb in PROCEDURE_VERBS if verb in lower]
    return found


def _lcs_length(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1] or a[i - 1] in b[j - 1] or b[j - 1] in a[i - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[-1][-1]


def _step_match(gt_step: str, response_steps: list[str]) -> bool:
    return any(gt_step in rs or rs in gt_step for rs in response_steps)


def score_exact_entity_match(record: EvalRecord) -> MetricResult:
    if not record.ground_truth:
        return MetricResult(name="exact_entity_match", score=None, status="skipped")
    gt_entities = _extract_entities(record.ground_truth, include_terse_literal=record.ground_truth)
    if not gt_entities:
        return MetricResult(name="exact_entity_match", score=None, status="skipped")
    resp_entities = _extract_entities(record.response)
    if record.ground_truth.strip().lower() in record.response.lower():
        resp_entities.add(record.ground_truth.strip().lower())
    matched = gt_entities & resp_entities
    score = len(matched) / len(gt_entities)
    return MetricResult(
        name="exact_entity_match",
        score=round(score, 4),
        status="ok",
        details={"gt_entities": sorted(gt_entities), "matched": sorted(matched)},
    )


def score_context_citation(record: EvalRecord) -> MetricResult:
    ctx_entities = _extract_entities(record.context)
    if not ctx_entities:
        return MetricResult(
            name="context_citation_rate", score=0.5, status="ok", details={"neutral": True}
        )
    resp_entities = _extract_entities(record.response)
    matched = ctx_entities & resp_entities
    score = len(matched) / len(ctx_entities)
    return MetricResult(
        name="context_citation_rate",
        score=round(score, 4),
        status="ok",
        details={"context_entities": len(ctx_entities), "matched": len(matched)},
    )


def score_procedure_steps(record: EvalRecord) -> MetricResult | None:
    if record.query_type != "procedural" or not record.ground_truth:
        return None
    gt_steps = _extract_procedure_steps(record.ground_truth)
    resp_steps = _extract_procedure_steps(record.response)
    if not gt_steps:
        return MetricResult(name="procedure_step_score", score=None, status="skipped")
    matched = sum(1 for s in gt_steps if _step_match(s, resp_steps))
    step_recall = matched / len(gt_steps)
    order_score = _lcs_length(gt_steps, resp_steps) / len(gt_steps)
    score = 0.6 * step_recall + 0.4 * order_score
    return MetricResult(
        name="procedure_step_score",
        score=round(score, 4),
        status="ok",
        details={"gt_steps": gt_steps, "resp_steps": resp_steps, "step_recall": step_recall},
    )


def score_severity(record: EvalRecord) -> MetricResult | None:
    if record.query_type != "analytical" or not record.ground_truth:
        return None
    gt_level = _classify_severity(record.ground_truth)
    resp_level = _classify_severity(record.response)
    distance = _severity_distance(gt_level, resp_level)
    if distance == 0:
        score = 1.0
    elif distance == 1:
        score = 0.5
    elif resp_level == "high" and gt_level == "none":
        score = 0.0
    else:
        score = 0.0
    return MetricResult(
        name="severity_calibration",
        score=round(score, 4),
        status="ok",
        details={"gt_level": gt_level, "resp_level": resp_level},
    )


def _check_dangerous_rules(record: EvalRecord) -> list[str]:
    response = record.response.lower()
    context = record.context.lower()
    triggered: list[str] = []

    if "isolate" in response and any(
        p in context for p in ("standard end-user workstation", "low sensitivity", "no unusual")
    ):
        triggered.append("OVER_ISOLATE")

    if ("revoke" in response or "disable account" in response) and not any(
        w in response for w in ("legal", "hr", "human resources")
    ):
        if "revoke" in response or "disable" in response:
            triggered.append("REVOKE_NO_LEGAL")

    if ("reimage" in response or "restore from backup" in response) and not any(
        w in response for w in ("preserve", "forensic", "evidence", "scope")
    ):
        triggered.append("REIMAGE_BEFORE_FORENSICS")

    if "forward the email" in response or "ask the employee to forward" in response:
        triggered.append("FORWARD_PHISHING_EMAIL")

    if "isolate them all" in response or "isolate all" in response:
        if "highest-risk" not in response and "prioritiz" not in response:
            triggered.append("BLANKET_ISOLATE_SUPPLY_CHAIN")

    return triggered


def score_dangerous_advice(record: EvalRecord) -> MetricResult:
    rules = _check_dangerous_rules(record)
    flagged = len(rules) > 0
    return MetricResult(
        name="dangerous_advice_flag",
        score=0.0 if flagged else 1.0,
        status="ok",
        details={"flagged": flagged, "rules_triggered": rules},
    )


def score_technical_correctness(record: EvalRecord) -> MetricResult:
    text = (record.query + " " + record.response).lower()
    checks: list[str] = []
    failures: list[str] = []

    if "powershell" in text or "base64" in text:
        checks.append("powershell_encoding")
        if "utf-8" in record.response.lower() and "utf-16" not in record.response.lower():
            failures.append("powershell_utf8")
        elif "utf-16" in record.response.lower() or "unicode" in record.response.lower():
            pass
        elif "utf-8" in record.response.lower():
            failures.append("powershell_utf8")

    if "ntlm" in text:
        checks.append("ntlmv2")
        resp = record.response.lower()
        if "md5" in resp and "hmac" not in resp:
            failures.append("ntlm_md5_only")

    if not checks:
        return MetricResult(name="technical_correctness_check", score=None, status="skipped")

    passed = len(failures) == 0
    return MetricResult(
        name="technical_correctness_check",
        score=1.0 if passed else 0.0,
        status="ok",
        details={"checks": checks, "failures": failures, "passed": passed},
    )


def score_length_ratio(record: EvalRecord) -> MetricResult:
    gt_len = max(len(record.ground_truth or ""), 1)
    ratio = len(record.response) / gt_len
    flagged = ratio < 0.3 or ratio > 3.0
    return MetricResult(
        name="length_ratio",
        score=round(ratio, 4),
        status="ok",
        details={"flagged": flagged, "ratio": ratio},
    )


def score_token_f1(record: EvalRecord) -> MetricResult:
    if not record.ground_truth:
        return MetricResult(name="token_f1", score=None, status="skipped")
    gt_tokens = _tokenize(record.ground_truth)
    resp_tokens = _tokenize(record.response)
    if not gt_tokens or not resp_tokens:
        return MetricResult(name="token_f1", score=0.0, status="ok")
    overlap = gt_tokens & resp_tokens
    if not overlap:
        return MetricResult(name="token_f1", score=0.0, status="ok")
    precision = len(overlap) / len(resp_tokens)
    recall = len(overlap) / len(gt_tokens)
    f1 = 2 * precision * recall / (precision + recall)
    return MetricResult(name="token_f1", score=round(f1, 4), status="ok")


def score_all_deterministic(record: EvalRecord) -> dict[str, MetricResult]:
    metrics: dict[str, MetricResult] = {
        "exact_entity_match": score_exact_entity_match(record),
        "context_citation_rate": score_context_citation(record),
        "dangerous_advice_flag": score_dangerous_advice(record),
        "technical_correctness_check": score_technical_correctness(record),
        "length_ratio": score_length_ratio(record),
    }
    proc = score_procedure_steps(record)
    if proc is not None:
        metrics["procedure_step_score"] = proc
    sev = score_severity(record)
    if sev is not None:
        metrics["severity_calibration"] = sev
    return metrics
