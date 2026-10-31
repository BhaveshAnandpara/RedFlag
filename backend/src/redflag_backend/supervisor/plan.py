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
    # A plain message when the plan cannot start, such as a rule that got no tests.
    blocked: str | None = None


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
            specs += book.take(goal, output, brief.environment)
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
                specs += book.take(goal, output, brief.environment)
            if len(specs) == before:
                break
        note = None
        if len(specs) < target:
            note = f"We could only find {len(specs)} truly different attacks for this goal."
        if goal.background:
            specs = specs[:background_left]
            background_left -= len(specs)
        planned.append(PlannedGoal(goal=goal, target=target, specs=specs, note=note))
    if progress is not None:
        progress.working_on("Putting the plan together")
    return _finish(planned, fear, book)


def _finish(planned: list[PlannedGoal], fear: Goal | None, book: _Book) -> Plan:
    empty = [p.goal for p in planned if p.goal.source == "user" and not p.specs]
    blocked = None
    if empty:
        rules = "; ".join(f"“{g.rule}”" for g in empty)
        failed = {c.persona_id for c in book.counts.values() if c.failed}
        if any(set(g.persona_ids) & failed for g in empty):
            blocked = (
                f"We could not write any test for: {rules}, because the AI models did not "
                "answer. Wait a few minutes and plan again."
            )
        else:
            blocked = (
                f"We could not write any test for: {rules}. Reword the rule or take it out, "
                "then plan again."
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
        blocked=blocked,
    )
