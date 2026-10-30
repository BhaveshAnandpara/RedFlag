"""The supervisor: a planner, not a judge.

It turns the interview's rules and Recon's fact sheet into plain-language goals, hands each goal to
the personas that fit, collects their tests, removes repeats, balances how many tests a goal gets
by how much the user cares, and orders the plan by impact. It never decides whether a test broke.
"""
