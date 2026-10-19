"""Combining the plain rules' verdict with the AI judge's into one result.

Either side saying FAIL makes the test FAIL. A pass that the judge could not double-check is
never shown as a pass: it becomes inconclusive. The combined text always names its sources, so
the rules' and the judge's own words stay visible side by side.
"""

from redflag_backend.judge.judge import JudgeVerdict
from redflag_backend.scan.checks import Verdict


def combine(rules: Verdict, judge: JudgeVerdict) -> tuple[str, str]:
    """The combined status and a readable explanation that names where each part came from."""
    rule_part = f"Plain rules ({rules.status.upper()}): {rules.evidence}."
    judge_part = f"AI judge ({judge.status.upper()}): {judge.reason}"
    if not judge_part.endswith("."):
        judge_part += "."

    if rules.status == "fail":
        return "fail", f"{rule_part} {judge_part}"
    if judge.status == "fail":
        return "fail", f"{rule_part} {judge_part}"
    if judge.status == "unavailable":
        note = (
            "The pass was not double-checked by the AI judge."
            if rules.status == "pass"
            else "Neither could decide this test."
        )
        return "inconclusive", f"{rule_part} {judge_part} {note}"
    if rules.status == "inconclusive":
        return (
            "pass",
            f"{rule_part} The plain rules were unsure, so the AI judge decided. {judge_part}",
        )
    return "pass", f"{rule_part} {judge_part}"
