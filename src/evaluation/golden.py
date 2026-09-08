from __future__ import annotations

import json
from pathlib import Path


GOLDEN_PATH = Path(__file__).resolve().parents[2] / "evals" / "golden.json"
REQUIRED_FIELDS = {"id", "category", "input", "expected"}


def load_golden_set(path: Path = GOLDEN_PATH) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("golden set root must be a list")
    return data


def validate_golden_set(cases: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, case in enumerate(cases):
        missing = REQUIRED_FIELDS - set(case)
        if missing:
            errors.append(f"case {index} missing: {', '.join(sorted(missing))}")
        case_id = str(case.get("id", ""))
        if case_id in seen:
            errors.append(f"duplicate id: {case_id}")
        seen.add(case_id)
        if not isinstance(case.get("expected"), dict) or not case.get("expected"):
            errors.append(f"case {case_id or index} has no expectations")
    return errors
