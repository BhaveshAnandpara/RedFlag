"""The contract between a spec and its result: what a finished test must fill in.

A spec is the promise; a result is the proof. This module writes down what the result must hold and
the trust rules, once, so the result record (ticket 11) and the report build to it and are tested
from the other side:

- A result points to its spec by ID and hash, so it always says exactly what was promised.
- A decided result (Broke, Held, Needs review) needs the full conversation, a reason, and a replay:
  the attacker's own messages, stored apart from the bot's replies, so replaying is a lookup.
- A Broke names the turn where it broke, and that turn is a reply from the bot.
- Every decided result says how sure it is.
- A test whose real user asked for the action cannot be marked Broke.
"""

from typing import Literal

from pydantic import BaseModel, Field

from redflag_backend.specs.oracle import Turn
from redflag_backend.specs.store import StoredSpec

Outcome = Literal["broke", "held", "refused", "couldnt_test", "skipped", "needs_review"]
HowSure = Literal["confirmed_by_logs", "confirmed_by_checks", "reply_only", "couldnt_confirm"]
Compared = Literal["new", "still_broken", "fixed", "first_run"]

# Outcomes that say something about the bot and so must show their proof.
DECIDED: set[str] = {"broke", "held", "needs_review"}


class ResultRecord(BaseModel):
    """Everything a finished test must fill in. Ticket 11 stores exactly this."""

    spec_id: str
    spec_hash: str
    outcome: Outcome
    what_happened: str = ""
    conversation: list[Turn] = Field(default_factory=list)
    # The attacker's own messages, stored apart from the bot's replies so a replay is a lookup.
    attacker_messages: list[str] = Field(default_factory=list)
    broke_at_turn: int | None = None  # index into `conversation`
    action_seen: str | None = None
    extra_proof: str | None = None
    how_sure: HowSure | None = None
    reason: str = ""
    repeat_count: int = Field(default=1, ge=1)
    repeats_broke: int = Field(default=0, ge=0)
    compared_with_last: Compared | None = None
    severity: str | None = None
    fix: str = ""
    bot_version: str | None = None  # the version of the user's server that was tested


def problems(result: ResultRecord, spec: StoredSpec) -> list[str]:
    """Why this result is invalid, in plain words. Empty when it keeps the contract."""
    found: list[str] = []
    if result.spec_id != spec.spec_id or result.spec_hash != spec.hash:
        found.append("The result does not point at this spec's ID and hash.")
    if not result.reason.strip():
        found.append("The result gives no reason.")
    if result.repeats_broke > result.repeat_count:
        found.append("More repeats broke than were run.")
    if result.outcome not in DECIDED:
        return found
    if not result.conversation:
        found.append("A decided result needs the full conversation.")
    if not result.attacker_messages:
        found.append("A decided result needs a replay: the attacker's messages are missing.")
    else:
        sent = [t.content for t in result.conversation if t.role == "user"]
        if sent != result.attacker_messages:
            found.append(
                "The saved attacker messages do not match the conversation: a replay would differ."
            )
    if result.how_sure is None:
        found.append("A decided result must say how sure it is.")
    if result.outcome == "broke":
        turn = result.broke_at_turn
        if turn is None or not 0 <= turn < len(result.conversation):
            found.append("A Broke must name the turn where it broke.")
        elif result.conversation[turn].role != "assistant":
            found.append("The turn where it broke must be a reply from the bot.")
        if result.how_sure == "couldnt_confirm":
            found.append("A Broke cannot be one the result could not confirm.")
        if result.action_seen and result.action_seen in spec.spec.user_requested_actions:
            found.append(
                f"The real user asked for “{result.action_seen}”, so this cannot be marked Broke."
            )
    return found


def is_valid(result: ResultRecord, spec: StoredSpec) -> bool:
    return not problems(result, spec)
