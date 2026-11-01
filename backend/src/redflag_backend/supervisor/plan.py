"""The plan: goals, the personas' tests for each, balanced by how much the user cares.

How many tests a goal gets depends on its importance, not on how many the personas happened to
write. The numbers below are guesses to tune after real runs. A goal that falls short is topped up
by asking the personas for different angles, at most three rounds, and if no more truly different
tests exist the plan says so. Priority only sets the order: nothing is cut for budget.
"""

import asyncio
import math
import re

from pydantic import BaseModel, Field

from redflag_backend.personas.merge import NEEDS_TEST_COPY, Count, Skipped, needs_test_copy
from redflag_backend.personas.registry import PERSONAS
from redflag_backend.personas.writer import MAX_DRAFTS, Brief, Dropped, PersonaTests, write_tests
from redflag_backend.quick.logs import NO_SETUP
from redflag_backend.setups.llm import SetupLLM
from redflag_backend.specs.spec import TestSpec
from redflag_backend.supervisor.goals import SEVERITY_RANK, Goal, make_goals
from redflag_backend.supervisor.progress import Progress
from redflag_backend.validator.loop import Rejection, Stats, check_goal

BIGGEST_FEAR_MIN = 30
CRITICAL_MIN = 15
MAX_ROUNDS = 3
BACKGROUND_CAP = 10
FIRST_ROUND_MIN = 3
BACKGROUND_EACH = 4
SEEN_IN_PROMPT = 5


class Removed(BaseModel):
    goal_id: str
    persona: str
    goal: str
    reason: str


class PlannedGoal(BaseModel):
    goal: Goal
    target: int
    specs: list[TestSpec] = Field(default_factory=list)
    # Said when the goal could not reach its target: "we could only find 12 truly different ones".
    note: str | None = None


class Summary(BaseModel):
    ideas: int
    repeats_removed: int
    tests: int
    data_changing: int


class Plan(BaseModel):
    goals: list[PlannedGoal]
    biggest_fear: str | None
    summary: Summary
    removed: list[Removed] = Field(default_factory=list)
    dropped: list[Dropped] = Field(default_factory=list)
    skipped: list[Skipped] = Field(default_factory=list)
    counts: list[Count] = Field(default_factory=list)
    # The rules the user gave that got no test, and a plain message about them. They do not stop
    # the plan: the tests that were written still run, and the report lists these as not tested.
    untested_rules: list[str] = Field(default_factory=list)
    warning: str | None = None
    # The rule check (ticket 12): tests it sent back, what it found overall, and why it did not run.
    rejections: list[Rejection] = Field(default_factory=list)
    checks: Stats = Field(default_factory=Stats)
    check_problem: str | None = None


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _idea(spec: TestSpec) -> tuple[str, str, str, tuple[str, ...]] | None:
    """The same idea whatever the wording: same persona, approach, mode and target route. A test
    with no stated approach cannot be compared this way, so only its words are compared."""
    if not spec.strategy or not _words(spec.strategy):
        return None
    return (spec.persona, _words(spec.strategy), spec.mode, tuple(sorted(spec.tools_involved)))


def _biggest_fear(goals: list[Goal]) -> Goal | None:
    """The user's biggest fear. They are not asked yet, so severity decides, then their own rules
    before ones we added, then the order the goals came in."""
    real = [(i, g) for i, g in enumerate(goals) if not g.background and g.severity]
    if not real:
        return None
    return min(
        real,
        key=lambda item: (
            SEVERITY_RANK[item[1].severity or "medium"],
            item[1].source != "user",
            item[0],
        ),
    )[1]


def _target(goal: Goal, fear: Goal | None) -> int:
    if fear is not None and goal.id == fear.id:
        return BIGGEST_FEAR_MIN
    if goal.severity == "critical":
        return CRITICAL_MIN
    return 0


class _Book:
    """What has been kept so far, so a repeat is found across goals, and the counts."""

    def __init__(self) -> None:
        self.openings: set[str] = set()
        self.ideas: set[tuple[str, str, str, tuple[str, ...]]] = set()
        self.removed: list[Removed] = []
        self.dropped: list[Dropped] = []
        self.skipped: list[Skipped] = []
        self.ideas_written = 0
        self.counts: dict[str, Count] = {}

    def count(self, persona_id: str) -> Count:
        persona = PERSONAS[persona_id]
        return self.counts.setdefault(
            persona_id,
            Count(
                persona_id=persona_id,
                persona=persona.name,
                written=0,
                dropped=0,
                after_repeats_removed=0,
            ),
        )

    def take(self, goal: Goal, output: PersonaTests, environment: str) -> list[TestSpec]:
        """The new tests from one persona call: set aside, deduplicated, counted."""
        count = self.count(output.persona_id)
        name = PERSONAS[output.persona_id].name
        count.written += len(output.specs)
        count.dropped += len(output.dropped)
        count.failed = count.failed or output.failed
        self.dropped += output.dropped
        self.ideas_written += len(output.specs)
        kept: list[TestSpec] = []
        for spec in output.specs:
            if environment == "production" and needs_test_copy(spec):
                self.skipped.append(Skipped(persona=name, goal=spec.goal, reason=NEEDS_TEST_COPY))
                count.after_repeats_removed += 1
                continue
            opening, idea = _words(spec.opening_message), _idea(spec)
            if opening in self.openings:
                reason = "Same opening message as an earlier test."
            elif idea is not None and idea in self.ideas:
                reason = "Same idea as an earlier test: same persona, approach, mode and tools."
            else:
                self.openings.add(opening)
                if idea is not None:
                    self.ideas.add(idea)
                count.after_repeats_removed += 1
                kept.append(spec)
                continue
            self.removed.append(
                Removed(goal_id=goal.id, persona=name, goal=spec.goal, reason=reason)
            )
        return kept


async def _ask(
    llm: SetupLLM,
    brief: Brief,
    goal: Goal,
    wanted: int,
    avoid: list[str],
    setup_id: int,
    progress: Progress | None,
) -> list[PersonaTests]:
    """One round: every persona that fits the goal writes its share."""
    share = max(FIRST_ROUND_MIN, math.ceil(wanted / len(goal.persona_ids)))
    share = min(share, MAX_DRAFTS)
    text = goal.question
    if avoid:
        text += " Find different angles from these openings already written: " + " | ".join(avoid)
    patience = progress.patience if progress else None

    async def one(persona_id: str) -> PersonaTests:
        written = await write_tests(
            llm,
            PERSONAS[persona_id],
            brief,
            goals=[text],
            count=share,
            setup_id=setup_id,
            patience=patience,
            risk=goal.risk,
        )
        if progress is not None:
            name = PERSONAS[persona_id].name
            if written.failed:
                progress.say(f"The {name} could not answer ({written.failed.replace('_', ' ')}).")
            else:
                progress.say(f"The {name} wrote {len(written.specs)} tests.")
        return written

    return list(await asyncio.gather(*(one(pid) for pid in goal.persona_ids)))


def _ordered(goals: list[Goal]) -> list[Goal]:
    """Scariest first; the user's own worries before ours at the same level; background last."""

    def key(item: tuple[int, Goal]) -> tuple[int, int, int, int]:
        i, g = item
        return (
            int(g.background),
            SEVERITY_RANK.get(g.severity or "medium", 2),
            int(g.source != "user"),
            i,
        )

    return [g for _, g in sorted(enumerate(goals), key=key)]


async def build_plan(
    llm: SetupLLM,
    brief: Brief,
    setup_id: int = NO_SETUP,
    progress: Progress | None = None,
) -> Plan:
    if progress is not None:
        progress.working_on("Reading your rules and what your bot said about itself")
        progress.say("Asking the planner what your bot should be tested for…")
    goals = _ordered(
        await make_goals(llm, brief, setup_id, progress.patience if progress else None)
    )
    if progress is not None:
        progress.say(f"Found {len(goals)} goals to test, scariest first.")
    fear = _biggest_fear(goals)
    book = _Book()
    planned: list[PlannedGoal] = []
    background_left = BACKGROUND_CAP
    for number, goal in enumerate(goals, start=1):
        if progress is not None:
            progress.goal(number, len(goals), goal.question)
        target = _target(goal, fear)
        wanted = BACKGROUND_EACH if goal.background else max(target, FIRST_ROUND_MIN)
        specs: list[TestSpec] = []
        if progress is not None:
            progress.asking(goal.persona_ids)
        for output in await _ask(llm, brief, goal, wanted, [], setup_id, progress):
            kept = book.take(goal, output, brief.environment)
            _show(progress, goal, kept, _room(goal, background_left, specs))
            specs += kept
        rounds = 0
        while len(specs) < target and rounds < MAX_ROUNDS:
            rounds += 1
            before = len(specs)
            avoid = [s.opening_message[:80] for s in specs[-SEEN_IN_PROMPT:]]
            if progress is not None:
                progress.say(f"Only {len(specs)} of {target} so far.")
                progress.asking(goal.persona_ids, rounds)
            for output in await _ask(
                llm, brief, goal, target - len(specs), avoid, setup_id, progress
            ):
                kept = book.take(goal, output, brief.environment)
                _show(progress, goal, kept, _room(goal, background_left, specs))
                specs += kept
            if len(specs) == before:
                break
        note = None
        if len(specs) < target:
            note = f"We could only find {len(specs)} truly different attacks for this goal."
            if progress is not None:
                progress.say(note)
        if goal.background:
            specs = specs[:background_left]
            background_left -= len(specs)
        planned.append(PlannedGoal(goal=goal, target=target, specs=specs, note=note))
    rejections, checks, check_problem = await _check_rules(llm, brief, planned, setup_id, progress)
    if progress is not None:
        progress.working_on("Putting the plan together")
        removed = len(book.removed)
        progress.say(
            f"Removed {removed} repeated {'idea' if removed == 1 else 'ideas'}."
            if removed
            else "No repeated ideas to remove."
        )
    plan = _finish(planned, fear, book)
    plan.rejections, plan.checks, plan.check_problem = rejections, checks, check_problem
    plan.summary.tests = sum(len(p.specs) for p in planned)
    plan.summary.data_changing = sum(1 for p in planned for s in p.specs if s.changes_data)
    if progress is not None:
        progress.say(
            "Some of your rules have no tests yet."
            if plan.warning
            else "Every one of your rules has at least one test."
        )
        progress.say(f"Plan ready: {plan.summary.tests} tests.")
    return plan


async def _check_rules(
    llm: SetupLLM,
    brief: Brief,
    planned: list[PlannedGoal],
    setup_id: int,
    progress: Progress | None,
) -> tuple[list[Rejection], Stats, str | None]:
    """Give every attack test a rule and an intention, and send back the ones that do not hold up.
    A goal that loses most of its tests says so, so the plan never claims coverage it lost."""
    rejections: list[Rejection] = []
    totals = Stats()
    problem: str | None = None
    numbers = iter(range(1, 10_000))
    if progress is not None:
        progress.working_on("Checking each test's rule")
        progress.say("Asking the rule writer how to tell, afterwards, whether each attack worked…")
    for number, item in enumerate(planned, start=1):
        if not item.specs:
            continue
        if progress is not None:
            progress.say(f"Checking the rules for goal {number} of {len(planned)}…")
        before = len(item.specs)
        checked = await check_goal(
            llm,
            brief,
            item.goal.id,
            item.specs,
            lambda: f"r-{next(numbers)}",
            setup_id,
            progress.patience if progress else None,
        )
        item.specs = checked.specs
        rejections += checked.rejections
        totals.add(checked.stats)
        problem = problem or checked.problem
        lost = before - len(item.specs)
        if lost and lost * 2 >= before:
            item.note = (item.note + " " if item.note else "") + (
                f"The rule check left out {lost} of this goal's {before} tests."
            )
    if progress is not None:
        if problem:
            progress.say("The rule writer could not answer for some tests. The judge decides them.")
        elif totals.fixed or totals.dropped:
            progress.say(
                f"{totals.fixed + totals.dropped} tests needed fixing: {totals.fixed} fixed "
                f"automatically, {totals.dropped} left out."
            )
        else:
            progress.say("Every rule passed its checks.")
    return rejections, totals, problem


def _room(goal: Goal, background_left: int, specs: list[TestSpec]) -> int | None:
    """How many more tests this goal may still show: the background checks are capped."""
    return max(0, background_left - len(specs)) if goal.background else None


def _show(progress: Progress | None, goal: Goal, kept: list[TestSpec], limit: int | None) -> None:
    """Add each new test to the page as a card, in the order it was written."""
    if progress is None:
        return
    for spec in kept[:limit]:
        persona_id = next(p.id for p in PERSONAS.values() if p.name == spec.persona)
        progress.test(
            persona_id, spec.persona, goal.question, spec.opening_message, spec.changes_data
        )


def _finish(planned: list[PlannedGoal], fear: Goal | None, book: _Book) -> Plan:
    wanted = [p for p in planned if p.goal.source == "user"]
    empty = [p.goal for p in wanted if not p.specs]
    untested = [g.rule for g in empty if g.rule]
    warning = None
    if empty:
        many = len(empty) > 1
        rules = "; ".join(f"“{rule}”" for rule in untested)
        failed = {c.persona_id for c in book.counts.values() if c.failed}
        warning = (
            f"{len(empty)} of your {len(wanted)} rules {'have' if many else 'has'} no tests: "
            f"{rules}. The tests we did write will still run, and the report will list "
            f"{'these rules' if many else 'this rule'} as not tested. "
        )
        if any(set(g.persona_ids) & failed for g in empty):
            warning += (
                f"The AI models did not answer for {'them' if many else 'it'}: create the plan "
                "again in a few minutes to cover "
                f"{'them' if many else 'it'}."
            )
        else:
            warning += (
                f"Reword {'them' if many else 'it'} and create the plan again to cover "
                f"{'them' if many else 'it'}."
            )
    tests = [s for p in planned for s in p.specs]
    return Plan(
        goals=planned,
        biggest_fear=fear.question if fear else None,
        summary=Summary(
            ideas=book.ideas_written,
            repeats_removed=len(book.removed),
            tests=len(tests),
            data_changing=sum(1 for s in tests if s.changes_data),
        ),
        removed=book.removed,
        dropped=book.dropped,
        skipped=book.skipped,
        counts=list(book.counts.values()),
        untested_rules=untested,
        warning=warning,
    )
