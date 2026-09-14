#!/usr/bin/env python3
"""Evaluate recorded outputs against the product golden set.

Without ``--responses`` only locally deterministic safety cases can execute.
An incomplete run exits non-zero so partial coverage can never look green.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluation.golden import (
    EvaluationOutput,
    evaluate_case,
    load_golden_set,
    validate_golden_set,
)
from src.services.safety import SafetyPolicy


def load_recorded_outputs(path: Path) -> dict[str, EvaluationOutput]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("recorded outputs root must be an object keyed by case id")
    invalid = [str(case_id) for case_id, value in raw.items() if not isinstance(value, dict)]
    if invalid:
        raise ValueError(f"recorded outputs must be objects: {', '.join(invalid)}")
    return {str(case_id): EvaluationOutput.from_mapping(value) for case_id, value in raw.items()}


def build_report(
    cases: list[dict],
    recorded_outputs: dict[str, EvaluationOutput] | None = None,
) -> dict:
    errors = validate_golden_set(cases)
    if errors:
        return {
            "cases": len(cases),
            "executed": 0,
            "missing": len(cases),
            "failed": 0,
            "coverage_complete": False,
            "passed": False,
            "schema_errors": errors,
            "unexpected_outputs": [],
            "results": [],
        }
    safety = SafetyPolicy()
    outputs = dict(recorded_outputs or {})
    case_ids = {case["id"] for case in cases}
    unexpected_outputs = sorted(set(outputs) - case_ids)

    # SafetyPolicy is deterministic and can be evaluated without a model run.
    for case in cases:
        expected_state = case["expected"].get("safety_state")
        if expected_state and case["id"] not in outputs:
            decision = safety.evaluate(case["input"])
            # A crisis response is fully produced by the deterministic policy.
            # A supportive redirect still needs the model's final response, so
            # it remains missing unless a completed output was recorded.
            if decision.response is not None:
                outputs[case["id"]] = EvaluationOutput(
                    response_text=decision.response,
                    safety_state=decision.state,
                )

    results = []
    for case in cases:
        output = outputs.get(case["id"])
        if output is None:
            results.append({
                "id": case["id"],
                "category": case["category"],
                "status": "missing",
                "checks": [],
            })
            continue
        checks = evaluate_case(case, output) if not errors else []
        passed = bool(checks) and all(check.passed for check in checks)
        results.append({
            "id": case["id"],
            "category": case["category"],
            "status": "passed" if passed else "failed",
            "checks": [check.__dict__ for check in checks],
        })

    executed = sum(result["status"] != "missing" for result in results)
    failed = sum(result["status"] == "failed" for result in results)
    missing = len(cases) - executed
    coverage_complete = executed == len(cases)
    passed = not errors and coverage_complete and failed == 0
    return {
        "cases": len(cases),
        "executed": executed,
        "missing": missing,
        "failed": failed,
        "coverage_complete": coverage_complete,
        "passed": passed,
        "schema_errors": errors,
        "unexpected_outputs": unexpected_outputs,
        "results": results,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--responses",
        type=Path,
        help=(
            "JSON object keyed by golden case id with response_text, instruct_text, "
            "safety_state and optional semantic judgments"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    recorded = load_recorded_outputs(args.responses) if args.responses else None
    report = build_report(load_golden_set(), recorded)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["passed"]:
        return 0
    return 2 if not report["coverage_complete"] and not report["schema_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
