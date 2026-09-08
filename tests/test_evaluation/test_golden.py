import json

from src.evaluation.golden import load_golden_set, validate_golden_set
from scripts.evaluate import build_report


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


def test_evaluation_report_marks_unexecuted_cases_as_skipped():
    report = build_report(load_golden_set())

    assert report["executed"] == 2
    assert report["skipped"] == report["cases"] - report["executed"]
    assert report["coverage_complete"] is False
    assert "passed" not in report
