# Golden evaluation

`golden.json` defines the product regression cases and their expectations.
The evaluator is fail-closed: missing outputs, missing semantic judgments,
unsupported expectations, and failed checks can never produce a passing report.

Run deterministic checks only:

```bash
python scripts/evaluate.py
```

This normally returns exit code `2` because cases that require a model output
are intentionally reported as missing. To evaluate a completed run, provide a
JSON object keyed by case ID:

```json
{
  "known-fact-001": {
    "response_text": "她最喜欢桂花糕。",
    "instruct_text": "用温和的语气说话。",
    "safety_state": "normal",
    "judgments": {
      "must_not_claim_unknown_facts": true
    }
  }
}
```

```bash
python scripts/evaluate.py --responses path/to/responses.json
```

Exit codes:

- `0`: complete coverage and every expectation passed.
- `1`: a schema error or failed expectation.
- `2`: incomplete coverage.

Semantic negative assertions require an explicit verdict in `judgments`.
This prevents a short denylist from being mistaken for a reliable hallucination
or safety evaluation. The producer may be a reviewed human annotation or a
separate versioned judge; the evaluator treats a missing verdict as failure.
