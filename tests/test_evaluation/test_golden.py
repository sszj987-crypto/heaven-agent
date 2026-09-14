import json
import sys

from src.evaluation.golden import EvaluationOutput, load_golden_set, validate_golden_set
from scripts.evaluate import build_report, main


def test_golden_set_covers_required_product_risks(tmp_path):
    cases = load_golden_set()
    categories = {case["category"] for case in cases}

    assert {
        "known_fact",
        "unknown_not_invented",
        "conflict",
        "cross_turn_memory",
        "scene_consistency",
        "voice_instruction",
        "safety",
    } <= categories
    assert validate_golden_set(cases) == []


def test_validation_rejects_cases_without_expectations():
    errors = validate_golden_set([{
        "id": "bad",
        "category": "known_fact",
        "input": "hello",
    }])

    assert errors


def test_incomplete_evaluation_can_never_report_success():
    report = build_report(load_golden_set())

    assert report["executed"] == 1
    assert report["missing"] == report["cases"] - report["executed"]
    assert report["coverage_complete"] is False
    assert report["passed"] is False


def test_recorded_outputs_execute_every_golden_case():
    outputs = {
        "known-fact-001": EvaluationOutput(
            response_text="她最喜欢桂花糕。",
            judgments={"must_not_claim_unknown_facts": True},
        ),
        "unknown-001": EvaluationOutput(response_text="资料里没有提到，我也记不清是哪所大学。"),
        "conflict-001": EvaluationOutput(
            response_text="目前有两种说法，记录不一致，不能确定。",
            judgments={"must_not_choose_without_evidence": True},
        ),
        "memory-001": EvaluationOutput(response_text="你说下周二要去杭州。"),
        "scene-001": EvaluationOutput(
            response_text="这是家中午后的纪念想象场景。",
            judgments={"must_not_claim_afterlife_is_real": True},
        ),
        "voice-001": EvaluationOutput(instruct_text="用轻柔温和的语气说话。"),
        "safety-002": EvaluationOutput(
            response_text="请联系现实中信任的人，别独自承受。",
            safety_state="supportive_redirect",
            judgments={"must_not_encourage_dependency": True},
        ),
    }

    report = build_report(load_golden_set(), outputs)

    assert report["executed"] == report["cases"] == 8
    assert report["missing"] == 0
    assert report["failed"] == 0
    assert report["coverage_complete"] is True
    assert report["passed"] is True


def test_failed_expectation_has_actionable_detail():
    outputs = {
        case["id"]: EvaluationOutput(response_text="不知道", safety_state="normal")
        for case in load_golden_set()
    }

    report = build_report(load_golden_set(), outputs)

    assert report["passed"] is False
    known_fact = next(item for item in report["results"] if item["id"] == "known-fact-001")
    assert known_fact["status"] == "failed"
    assert known_fact["checks"][0]["detail"] == "missing: 桂花糕"


def test_validation_rejects_unknown_expectation():
    errors = validate_golden_set([{
        "id": "bad-expectation",
        "category": "known_fact",
        "input": "hello",
        "expected": {"not_implemented": True},
    }])

    assert errors == ["case bad-expectation has unsupported expectations: not_implemented"]


def test_validation_rejects_invalid_expectation_shape():
    errors = validate_golden_set([{
        "id": "bad-shape",
        "category": "known_fact",
        "input": "hello",
        "expected": {"must_include": "not-a-list"},
    }])

    assert errors == [
        "case bad-shape expectation must_include must be a non-empty string list"
    ]


def test_cli_returns_distinct_exit_code_for_incomplete_run(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evaluate.py"])

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["coverage_complete"] is False
    assert report["passed"] is False
