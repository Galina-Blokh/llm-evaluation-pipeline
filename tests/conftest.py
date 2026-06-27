from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = ROOT / "tests" / "fixtures" / "agent_outputs.jsonl"
COMMITTED_OUTPUT = ROOT / "output" / "results.json"
COMMITTED_REPORT = ROOT / "output" / "report.md"


@pytest.fixture
def example_input() -> Path:
    if not EXAMPLE_INPUT.exists():
        pytest.skip("tests/fixtures/agent_outputs.jsonl not present")
    return EXAMPLE_INPUT


@pytest.fixture
def committed_results() -> Path:
    if not COMMITTED_OUTPUT.exists():
        pytest.skip("output/results.json not present")
    return COMMITTED_OUTPUT


@pytest.fixture
def committed_report() -> Path:
    if not COMMITTED_REPORT.exists():
        pytest.skip("output/report.md not present")
    return COMMITTED_REPORT
