"""Putting the personas' tests together: the skip rule, removing repeats, and per-persona counts.

Counts only say what each persona wrote and what was left of it. They do not judge a persona:
whether one earns its place needs many runs, so version 1 reports the numbers and flags only a
persona whose tests mostly collapsed into another's.
"""

import re

from pydantic import BaseModel

from redflag_backend.personas.registry import DOOR_MODE, PERSONAS
from redflag_backend.personas.writer import PersonaTests
from redflag_backend.specs.spec import TestSpec

NEEDS_TEST_COPY = "needs a test copy"
# A persona with at least this many tests, and under this share left, is flagged.
MIN_TO_FLAG = 3
SHARE_TO_FLAG = 0.5


class Skipped(BaseModel):
    persona: str
    goal: str
    reason: str


class Count(BaseModel):
    persona_id: str
    persona: str
    written: int
    dropped: int
    after_repeats_removed: int
    mostly_repeats: bool = False
    failed: str | None = None


class Merged(BaseModel):
    specs: list[TestSpec]
    skipped: list[Skipped]
    counts: list[Count]


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def needs_test_copy(spec: TestSpec) -> bool:
    """A test that plants data for the bot to read changes data, so it needs a test copy."""
    return spec.mode == DOOR_MODE["poisoned_content"]


def merge(written: list[PersonaTests], environment: str) -> Merged:
    """The tests to run, from every persona's output, in the personas' own order.

    In production nothing may be planted, so tests that plant data are set aside as "needs a test
    copy" rather than dropped silently. Two tests that open the same way, or aim at the same risk
    with the same goal, are one test: the first persona to write it keeps it.
    """
    order = {persona_id: i for i, persona_id in enumerate(PERSONAS)}
    written = sorted(written, key=lambda w: order.get(w.persona_id, len(order)))
    specs: list[TestSpec] = []
    skipped: list[Skipped] = []
    counts: list[Count] = []
    seen_opening: set[str] = set()
    seen_aim: set[tuple[str | None, str]] = set()
    for output in written:
        persona = PERSONAS[output.persona_id]
        after = 0
        for spec in output.specs:
            if environment == "production" and needs_test_copy(spec):
                skipped.append(
                    Skipped(persona=persona.name, goal=spec.goal, reason=NEEDS_TEST_COPY)
                )
                after += 1  # set aside, not a repeat
                continue
            opening, aim = _words(spec.opening_message), (spec.risk, _words(spec.goal))
            if opening in seen_opening or aim in seen_aim:
                continue
            seen_opening.add(opening)
            seen_aim.add(aim)
            specs.append(spec)
            after += 1
        total = len(output.specs)
        counts.append(
            Count(
                persona_id=persona.id,
                persona=persona.name,
                written=total,
                dropped=len(output.dropped),
                after_repeats_removed=after,
                mostly_repeats=total >= MIN_TO_FLAG and after / total < SHARE_TO_FLAG,
                failed=output.failed,
            )
        )
    return Merged(specs=specs, skipped=skipped, counts=counts)
