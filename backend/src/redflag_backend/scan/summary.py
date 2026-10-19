"""The "what we did and did not check" summary over the catalog's risks.

A risk counts as tested only when at least one of its tests ended pass or fail. A risk whose
tests all errored, were inconclusive or did not apply is "attempted, no result", never tested.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from redflag_backend.scan.catalog import Catalog

STATUSES = ("pass", "fail", "inconclusive", "error", "not_applicable")
DISCLAIMER = (
    "This is not a claim that the bot is secure. It lists what this scan checked and what it "
    "did not, and a pass only means no problem was found by these tests."
)


def zero_counts(counts: dict[str, int] | None = None) -> dict[str, int]:
    return {status: int((counts or {}).get(status, 0)) for status in STATUSES}


def summarize(results: Sequence[dict[str, Any]], catalog: Catalog) -> dict[str, Any]:
    counts = zero_counts(Counter(r["status"] for r in results))
    risks = []
    for risk in catalog.risks:
        mine = Counter(r["status"] for r in results if r["risk"] == risk.id)
        tests = sum(mine.values())
        if mine["pass"] + mine["fail"] > 0:
            state = "tested"
        elif tests > 0:
            state = "attempted_no_result"
        else:
            state = "not_tested"
        risks.append(
            {
                "id": risk.id,
                "name": risk.name,
                "state": state,
                "tests": tests,
                "passed": mine["pass"],
                "failed": mine["fail"],
                "errors": mine["error"],
                "inconclusive": mine["inconclusive"],
                "not_applicable": mine["not_applicable"],
            }
        )
    normal = Counter(r["status"] for r in results if r["kind"] == "positive")
    return {
        "counts": counts,
        "risks": risks,
        "normal_requests": {
            "tests": sum(normal.values()),
            "passed": normal["pass"],
            "failed": normal["fail"],
            "errors": normal["error"] + normal["inconclusive"] + normal["not_applicable"],
        },
        "catalog_version": catalog.version,
        "catalog_source": catalog.source,
        "disclaimer": DISCLAIMER,
    }
