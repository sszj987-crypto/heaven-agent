#!/usr/bin/env python3
"""Run deterministic local checks for the golden evaluation set."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluation.golden import load_golden_set, validate_golden_set
from src.services.safety import SafetyPolicy


def build_report(cases: list[dict]) -> dict:
    errors = validate_golden_set(cases)
    safety = SafetyPolicy()
    checks = []
    for case in cases:
        expected_state = case["expected"].get("safety_state")
        if expected_state:
            actual = safety.evaluate(case["input"]).state
            checks.append({
                "id": case["id"],
                "expected": expected_state,
                "actual": actual,
                "passed": actual == expected_state,
            })
    executed = len(checks)
    return {
        "cases": len(cases),
        "executed": executed,
        "skipped": len(cases) - executed,
        "coverage_complete": executed == len(cases),
        "schema_errors": errors,
        "deterministic_checks": checks,
        "deterministic_passed": not errors and all(item["passed"] for item in checks),
    }


def main() -> int:
    report = build_report(load_golden_set())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["deterministic_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
