from __future__ import annotations

import pytest

from eval_pipeline.judge.parser import parse_judge_response


def test_parse_clean_json():
    raw = json_response(
        overall=4,
        groundedness=5,
        safety=4,
        procedure=3,
        context_use=4,
        reasoning="Good answer",
        flags=["over_alerting"],
    )
    result = parse_judge_response(raw, provider="openai")
    assert result.overall == 4
    assert result.groundedness == 5
    assert result.flags == ["over_alerting"]
    assert result.provider == "openai"


def test_parse_json_in_markdown_fence():
    inner = json_response(overall=2, reasoning="Bad")
    raw = f"```json\n{inner}\n```"
    result = parse_judge_response(raw, provider="groq", status="retried")
    assert result.overall == 2
    assert result.status == "retried"


def test_parse_clamps_scores():
    raw = json_response(overall=99, groundedness=-1)
    result = parse_judge_response(raw, provider="openai")
    assert result.overall == 5
    assert result.groundedness == 1


def test_parse_filters_unknown_flags():
    raw = json_response(flags=["over_alerting", "not_a_real_flag"])
    result = parse_judge_response(raw, provider="openai")
    assert result.flags == ["over_alerting"]


def test_parse_invalid_json_raises():
    with pytest.raises(ValueError, match="No JSON"):
        parse_judge_response("not json at all", provider="openai")


def json_response(**kwargs) -> str:
    import json

    data = {
        "groundedness": 3,
        "safety": 3,
        "procedure": 3,
        "context_use": 3,
        "overall": 3,
        "reasoning": "",
        "flags": [],
    }
    data.update(kwargs)
    return json.dumps(data)
