"""A plan as the page shows it: plain fields only, no spec internals."""

from typing import Any

from redflag_backend.supervisor.plan import Plan

MOVES_PER_GOAL = 40


def plan_view(plan: Plan) -> dict[str, Any]:
    covered = [p.goal.rule for p in plan.goals if p.goal.source == "user" and p.specs]
    return {
        "summary": plan.summary.model_dump(),
        "biggest_fear": plan.biggest_fear,
        "blocked": plan.blocked,
        "rules_covered": [rule for rule in covered if rule],
        "skipped": [s.model_dump() for s in plan.skipped],
        "goals": [
            {
                "id": p.goal.id,
                "question": p.goal.question,
                "tag": p.goal.tag,
                "source": p.goal.source,
                "background": p.goal.background,
                "severity": p.goal.severity,
                "target": p.target,
                "note": p.note,
                "test_count": len(p.specs),
                "tests": [
                    {
                        "persona": s.persona,
                        "goal": s.goal,
                        "opening_message": s.opening_message,
                        "changes_data": s.changes_data,
                    }
                    for s in p.specs[:MOVES_PER_GOAL]
                ],
            }
            for p in plan.goals
        ],
        "removed": [r.model_dump() for r in plan.removed],
        "counts": [c.model_dump() for c in plan.counts],
    }
