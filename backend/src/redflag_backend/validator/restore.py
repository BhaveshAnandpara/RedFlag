"""Putting back a test the rule check left out.

The test comes back as it was written, with no rule, so the AI judge alone decides it, and it is
marked as restored so the report says the user chose to keep it.
"""

from redflag_backend.supervisor.plan import Plan


def restore(plan: Plan, rejection_id: str) -> bool:
    """Put the test back into its goal. False if there is nothing to put back."""
    rejection = next((r for r in plan.rejections if r.id == rejection_id), None)
    if rejection is None or rejection.spec is None or rejection.restored:
        return False
    goal = next((p for p in plan.goals if p.goal.id == rejection.goal_id), None)
    if goal is None:
        return False
    goal.specs.append(rejection.spec.model_copy(update={"restored": True}))
    rejection.restored = True
    rejection.effect = "Put back by you. It runs on the AI judge alone."
    plan.summary.tests += 1
    plan.summary.data_changing += int(rejection.spec.changes_data)
    plan.checks.dropped = max(0, plan.checks.dropped - 1)
    return True
