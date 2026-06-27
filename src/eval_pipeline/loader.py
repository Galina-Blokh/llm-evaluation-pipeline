from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from eval_pipeline.models import EvalRecord, IngestError

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("query", "context", "response")


def classify_gt(ground_truth: str | None) -> Literal["valid", "partial_gt", "invalid_gt"]:
    if not ground_truth or not ground_truth.strip():
        return "invalid_gt"
    if len(ground_truth.strip()) <= 5:
        return "partial_gt"
    return "valid"


def normalize_raw_row(raw: dict, source_line: int) -> EvalRecord:
    metadata = raw.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    query_type = raw.get("query_type") or metadata.get("query_type")
    difficulty = raw.get("difficulty") or metadata.get("difficulty")
    ground_truth = raw.get("ground_truth")
    if ground_truth is not None:
        ground_truth = str(ground_truth).strip() or None

    record_id = raw.get("id") or f"line-{source_line:04d}"

    return EvalRecord(
        id=str(record_id),
        query=str(raw["query"]).strip(),
        context=str(raw["context"]).strip(),
        response=str(raw["response"]).strip(),
        ground_truth=ground_truth,
        query_type=str(query_type) if query_type else None,
        difficulty=str(difficulty) if difficulty else None,
        gt_status=classify_gt(ground_truth),
        source_line=source_line,
    )


def load_records(path: Path) -> tuple[list[EvalRecord], list[IngestError]]:
    records: list[EvalRecord] = []
    errors: list[IngestError] = []

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                msg = f"Malformed JSON on line {line_no}: {exc}"
                logger.warning(msg)
                errors.append(
                    IngestError(source_line=line_no, message=msg, raw_snippet=stripped[:120])
                )
                continue

            if not isinstance(raw, dict):
                msg = f"Expected JSON object on line {line_no}"
                logger.warning(msg)
                errors.append(IngestError(source_line=line_no, message=msg))
                continue

            missing = [f for f in REQUIRED_FIELDS if f not in raw or not str(raw[f]).strip()]
            if missing:
                msg = f"Missing required fields {missing} on line {line_no}"
                logger.warning(msg)
                errors.append(IngestError(source_line=line_no, message=msg))
                continue

            try:
                records.append(normalize_raw_row(raw, line_no))
            except Exception as exc:  # noqa: BLE001
                msg = f"Normalization failed on line {line_no}: {exc}"
                logger.warning(msg)
                errors.append(IngestError(source_line=line_no, message=msg))

    logger.info("Loaded %d records (%d ingest errors)", len(records), len(errors))
    return records, errors
