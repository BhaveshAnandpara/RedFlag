"""The test library: attack and normal-request tests as plain data, not code."""

from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

DEFAULT_SUITE_PATH = Path(__file__).with_name("data") / "suite-v2.json"


class Needs(BaseModel):
    """What a bot must have for a test to apply to it. A bot that lacks any of it is skipped."""

    model_config = ConfigDict(extra="forbid")

    tools: list[str] = []
    # Dotted paths into the bot's data, such as "orders.B-2001" or "articles.holiday-notice"
    data: list[str] = []


class CheckSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    params: dict[str, Any] = {}


class ScanTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    # The catalog risk this test covers. Normal-request (positive) tests cover none.
    risk: str | None = None
    kind: Literal["negative", "positive"]
    title: str
    message: str
    needs: Needs = Needs()
    # Approvals granted for this test (for example "refund:A-1002")
    approvals: list[str] = []
    check: CheckSpec
    # A rule id from the bot's policy, or plain text for a normal-request test
    rule: str
    # How serious a failure of this test is, and a short plain "how to fix this" note. Attack
    # tests carry both; normal-request tests carry neither. The owner edits them in the file.
    severity: Literal["critical", "high", "medium"] | None = None
    remediation: str | None = None

    @model_validator(mode="after")
    def _negative_tests_name_a_risk(self) -> Self:
        if self.kind == "negative" and not self.risk:
            raise ValueError(f"{self.id}: an attack test must name the risk it covers")
        return self


class Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_version: int
    tests: list[ScanTest]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        ids = [t.id for t in self.tests]
        if len(ids) != len(set(ids)):
            raise ValueError("test ids must be unique")
        return self


def load_suite(path: Path = DEFAULT_SUITE_PATH) -> Suite:
    return Suite.model_validate_json(path.read_text(encoding="utf-8"))
