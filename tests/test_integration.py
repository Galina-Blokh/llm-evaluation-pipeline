from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eval_pipeline.__main__ import parse_args, run_pipeline
from eval_pipeline.schema import validate_report_markdown, validate_results_file


def test_skip_judge_pipeline_writes_valid_outputs(example_input, tmp_path):
    out = tmp_path / "output"

    async def _run() -> int:
        args = parse_args(
            [
                "--input",
                str(example_input),
                "--output",
                str(out),
                "--skip-judge",
                "--log-level",
                "WARNING",
            ]
        )
        return await run_pipeline(args)

    code = asyncio.run(_run())
    assert code == 0

    results_path = out / "results.json"
    report_path = out / "report.md"
    chart_path = out / "chart.png"

    assert results_path.exists()
    assert report_path.exists()
    assert chart_path.exists()

    doc = validate_results_file(results_path)
    assert doc.health.degraded_mode == "deterministic_only"
    assert doc.health.rows_evaluated == 45
    assert len(doc.rows) == 45

    validate_report_markdown(report_path.read_text(encoding="utf-8"))

    assert chart_path.stat().st_size > 0


def test_skip_judge_known_row_scores(example_input, tmp_path):
    out = tmp_path / "output"

    async def _run() -> None:
        args = parse_args(
            [
                "--input",
                str(example_input),
                "--output",
                str(out),
                "--skip-judge",
                "--log-level",
                "WARNING",
            ]
        )
        await run_pipeline(args)

    asyncio.run(_run())
    doc = validate_results_file(out / "results.json")

    by_id = {r.id: r for r in doc.rows}
    a_e_003 = by_id["A-E-003"]
    assert a_e_003.critical_failure is True
    assert a_e_003.composite.score <= 0.2

    f_e_001 = by_id["F-E-001"]
    em = f_e_001.metrics["exact_entity_match"]
    assert em.score is not None
    assert em.score >= 0.9


def test_committed_chart_exists():
    chart = Path("output/chart.png")
    if not chart.exists():
        pytest.skip("output/chart.png not present")
    assert chart.stat().st_size > 1000
