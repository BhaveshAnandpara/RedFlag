"""How often the AI judge agrees with the owner's own labels. Counts only; no claim beyond them."""

from collections.abc import Sequence
from typing import Any

NOTE_EMPTY = (
    "The judge has not been checked for accuracy yet. Mark results in a scan as right or wrong "
    "to measure it."
)
NOTE = (
    "These numbers compare the judge with your own labels. They are only as good as the labels "
    "and the number of results they rest on."
)


def _count(rows: Sequence[tuple[str, str]]) -> dict[str, int]:
    return {
        "counted": len(rows),
        "agree": sum(1 for judged, correct in rows if judged == correct),
        # The judge said fail but the owner says the reply was fine.
        "false_alarms": sum(1 for j, c in rows if j == "fail" and c == "pass"),
        # The judge said pass but the owner says it broke the rule.
        "misses": sum(1 for j, c in rows if j == "pass" and c == "fail"),
    }


def accuracy(rows: Sequence[dict[str, Any]], min_sample: int) -> dict[str, Any]:
    """rows: one per labeled result, with risk, judge_status and correct."""
    judged = [r for r in rows if r["judge_status"] in ("pass", "fail")]
    total = _count([(r["judge_status"], r["correct"]) for r in judged])
    risks = []
    for risk in sorted({r["risk"] or "none" for r in judged}):
        mine = [(r["judge_status"], r["correct"]) for r in judged if (r["risk"] or "none") == risk]
        counts = _count(mine)
        risks.append(
            {
                "risk": risk,
                "labeled": len(mine),
                **counts,
                "agreement": counts["agree"] / len(mine),
                "small_sample": len(mine) < min_sample,
            }
        )
    return {
        "labeled": len(rows),
        "unjudged": len(rows) - len(judged),
        **total,
        "agreement": total["agree"] / total["counted"] if total["counted"] else None,
        "small_sample": total["counted"] < min_sample,
        "min_sample": min_sample,
        "risks": risks,
        "note": NOTE if rows else NOTE_EMPTY,
    }
