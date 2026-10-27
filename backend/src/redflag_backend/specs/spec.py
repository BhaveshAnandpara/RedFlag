"""The test spec: one record per test, the promise written before the run.

A spec is plain data. Its content decides its hash, so a result can say exactly which promise it
tested. Once the user approves the plan a spec is locked: a change makes a new version with a new
hash, never an edit (see `store.py`).

The oracle is the rule for Broke and Held, written against what the real user actually asked for,
never just "this tool was called". `real_user_problems` is the one place that rule is checked, so
validator (ticket 12) and the run both use the same code.
"""

import hashlib
import json
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from redflag_backend.setups.generator import CATALOG_IDS
from redflag_backend.setups.models import Severity
from redflag_backend.specs.oracle import (
    Oracle,
    Turn,
    broke_text,
    held_text,
    referenced_actions,
    too_deep,
)

# A direct call to a tool (A), a conversation with the bot (B), or poisoned data it reads (C).
# Bots reached over HTTP are only ever tested in B for now.
Mode = Literal["A", "B", "C"]
Kind = Literal["attack", "normal"]
MAX_TURNS = 20
MAX_REPEATS = 10


class SampleTranscript(BaseModel):
    """A made-up conversation the validator dry-runs the oracle on. Written by a separate call,
    never by whoever wrote the test, so one author never grades its own rule."""

    turns: list[Turn] = Field(min_length=1)
    expected: Literal["broke", "held"]


class Setup(BaseModel):
    """What the test plants before it starts: text for the bot to read, and named secrets."""

    planted_text: str | None = None
    canaries: dict[str, str] = Field(default_factory=dict)


class TestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    __test__: ClassVar[bool] = False  # a spec, not a test pytest should try to collect

    kind: Kind = "attack"
    persona: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1)
    mode: Mode = "B"
    tools_involved: list[str] = Field(default_factory=list)
    # What the real user actually asked the bot to do in this scenario: often nothing.
    user_requested: str | None = None
    user_requested_actions: list[str] = Field(default_factory=list)
    strategy: str | None = None
    setup: Setup = Field(default_factory=Setup)
    opening_message: str = Field(min_length=1)
    max_turns: int = Field(default=1, ge=1, le=MAX_TURNS)
    changes_data: bool = False
    repeats: int = Field(default=1, ge=1, le=MAX_REPEATS)
    rule: str | None = None  # the user's own words
    severity: Severity | None = None
    risk: str | None = None  # an OWASP LLM id such as LLM01
    fix_hint: str = ""
    oracle: Oracle | None = None
    samples: list[SampleTranscript] = Field(default_factory=list)

    @field_validator("persona", "goal", "opening_message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def _attacks_name_a_risk_and_severity(self) -> "TestSpec":
        if self.kind == "attack":
            if self.risk not in CATALOG_IDS:
                raise ValueError("an attack must name a risk from the catalog")
            if self.severity is None:
                raise ValueError("an attack needs a severity")
        else:
            self.risk = None
            self.severity = None
        return self

    @property
    def broke_if(self) -> str | None:
        """The Broke rule in plain words, generated from the oracle so there is one rule."""
        return broke_text(self.oracle) if self.oracle else None

    @property
    def held_if(self) -> str | None:
        return held_text(self.oracle) if self.oracle else None


def canonical(spec: TestSpec) -> str:
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def spec_hash(spec: TestSpec) -> str:
    """The same content always gives the same hash, so a result can name exactly this promise."""
    return hashlib.sha256(canonical(spec).encode("utf-8")).hexdigest()


def real_user_problems(spec: TestSpec) -> list[str]:
    """Why this spec could mark normal use as Broke, in plain words. Empty when it cannot."""
    if spec.oracle is None:
        return []
    asked = set(spec.user_requested_actions) & referenced_actions(spec.oracle.broke_if)
    problems = [
        f"The real user asked for “{action}”, so the Broke rule would flag normal use."
        for action in sorted(asked)
    ]
    if too_deep(spec.oracle):
        problems.append("The oracle is nested too deeply to read.")
    return problems


def from_generated(test: dict[str, Any], persona: str = "starter pack") -> TestSpec:
    """A spec for a test the generator or the starter pack already made. They have no rule a
    machine can check, so the oracle is empty and the judge decides, as it does today."""
    attack = test.get("kind") == "negative"
    return TestSpec(
        kind="attack" if attack else "normal",
        persona=persona,
        goal=test["goal"],
        strategy=test.get("strategy"),
        opening_message=test["prompt"],
        changes_data=bool(test.get("real_action", False)),
        rule=test.get("rule"),
        severity=test.get("severity"),
        risk=test.get("risk"),
        fix_hint=test.get("fix") or "",
    )
