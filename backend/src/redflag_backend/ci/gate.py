"""The CI gate: pass or fail by a severity threshold, without claiming more than the tests showed.

A pass only means that no test failed at or above the threshold. It always says how many tests
failed below it and how many were unclear, and it ends with the same not-a-guarantee line as the
dashboard. A run in which no test could be decided is an error, never a pass.
"""

from typing import Any

THRESHOLDS = ("critical", "high", "medium", "any")
RANK = {"critical": 0, "high": 1, "medium": 2}
CLOSING = "This is not a guarantee of security. It only reports what these tests checked."


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _at_or_above(result: dict[str, Any], fail_on: str) -> bool:
    if fail_on == "any":
        return True
    severity = result.get("severity")
    return severity in RANK and RANK[severity] <= RANK[fail_on]


def evaluate(scan: dict[str, Any], fail_on: str, fail_on_unclear: bool) -> dict[str, Any]:
    status = scan["scan"]["status"]
    results = scan["results"]
    if status == "running":
        return {
            "verdict": "running",
            "fail_on": fail_on,
            "fail_on_unclear": fail_on_unclear,
            "reasons": [],
            "message": "The run is still going.",
        }
    gate: dict[str, Any] = {"fail_on": fail_on, "fail_on_unclear": fail_on_unclear}
    decided = [r for r in results if r["status"] in {"pass", "fail"}]
    if status != "completed" or not decided:
        why = (
            "The run was interrupted, so there is no result."
            if status != "completed"
            else "The run could not be completed: every test ended in an error or was unclear, "
            "so there is no result."
        )
        return {**gate, "verdict": "error", "reasons": [why], "message": f"{why} {CLOSING}"}

    failed = [r for r in results if r["status"] == "fail"]
    blocking = [r for r in failed if _at_or_above(r, fail_on)]
    below = len(failed) - len(blocking)
    unclear = sum(1 for r in results if r["status"] in {"inconclusive", "error"})

    reasons = [
        f"{r['title']} ({r.get('severity') or 'not rated'}): "
        f"AI judge (FAIL): {r.get('judge_reason') or r['evidence']}"
        for r in blocking
    ]
    if fail_on_unclear and unclear > 0:
        reasons.append(f"{_count(unclear, 'test', 'tests')} could not be decided (unclear).")
    verdict = "fail" if reasons else "pass"

    level = "at any level" if fail_on == "any" else f"at or above the {fail_on} level"
    if blocking:
        parts = [f"{_count(len(blocking), 'test', 'tests')} failed {level}."]
    else:
        parts = [f"No test failed {level}."]
    if below:
        parts.append(f"{_count(below, 'test', 'tests')} failed below that level.")
    if unclear:
        verb = "was" if unclear == 1 else "were"
        parts.append(f"{unclear} {'test' if unclear == 1 else 'tests'} {verb} unclear.")
    parts.append(CLOSING)
    return {**gate, "verdict": verdict, "reasons": reasons, "message": " ".join(parts)}
