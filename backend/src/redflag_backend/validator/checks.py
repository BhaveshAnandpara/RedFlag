"""The code checks on one test's rule: what the validator decides without asking a model.

Each check returns plain-word problems; an empty list means the test passes. The checks are:
the rule is not a risk to run (no catastrophic pattern), it does not match the tester's own words
(a bot that merely repeats them would look broken), it never flags normal use, and it gets both
made-up chats right: Broke on the one that should fail, not Broke on the one that should hold.
"""

import re

from redflag_backend.specs.oracle import (
    All,
    Any_,
    Condition,
    Conversation,
    Not,
    ReplyContains,
    ReplyMatches,
    evaluate,
)
from redflag_backend.specs.spec import SampleTranscript, TestSpec, real_user_problems

# A group that repeats inside a repeat, such as (a+)+ : it can take forever on a long reply.
NESTED_REPEAT = re.compile(r"\([^()]*[+*][^()]*\)\s*(?:[+*]|\{\d+,\d*\})")
TRIVIAL = re.compile(r"^(?:\.[*+]|\.\{\d+,\d*\}|\\[sSwWdD][*+]|\[\^?[^\]]*\][*+])$")


def _leaves(condition: Condition) -> list[ReplyContains | ReplyMatches]:
    if isinstance(condition, ReplyContains | ReplyMatches):
        return [condition]
    if isinstance(condition, All | Any_):
        return [leaf for c in condition.of for leaf in _leaves(c)]
    if isinstance(condition, Not):
        return _leaves(condition.of)
    return []


def _own_words(spec: TestSpec) -> str:
    """Everything the tester put into the chat itself, which the bot may simply repeat."""
    return "\n".join(
        part for part in (spec.opening_message, spec.setup.planted_text or "") if part
    ).lower()


def rule_problems(spec: TestSpec) -> list[str]:
    """Why the Broke rule itself cannot be used, in plain words."""
    if spec.oracle is None:
        return []
    found: list[str] = []
    own = _own_words(spec)
    for leaf in _leaves(spec.oracle.broke_if):
        if isinstance(leaf, ReplyContains):
            if leaf.text.lower() in own:
                found.append(
                    f"The rule looks for “{leaf.text}”, which the tester itself wrote, so a bot "
                    "that only repeats it would be marked as broken."
                )
        else:
            if NESTED_REPEAT.search(leaf.pattern) or TRIVIAL.match(leaf.pattern.strip()):
                found.append(
                    f"The pattern “{leaf.pattern}” is too loose or too slow to trust on a reply."
                )
            elif re.search(leaf.pattern, own, re.IGNORECASE):
                found.append(
                    f"The pattern “{leaf.pattern}” matches text the tester itself wrote, so a "
                    "bot that only repeats it would be marked as broken."
                )
    return found


def sample_problems(spec: TestSpec) -> list[str]:
    """Run the rule on both made-up chats. A rule with samples that disagree with it is rejected."""
    if spec.oracle is None:
        return []
    kinds: dict[str, SampleTranscript] = {sample.expected: sample for sample in spec.samples}
    found: list[str] = []
    for expected, label in (("broke", "should fail"), ("held", "should hold")):
        sample = kinds.get(expected)
        if sample is None or not any(t.role == "assistant" for t in sample.turns):
            found.append(f"There is no usable chat that {label} to try the rule on.")
            continue
        outcome = evaluate(spec.oracle, Conversation(turns=sample.turns))
        if expected == "broke" and outcome.verdict != "broke":
            found.append(
                "On a chat where the bot clearly broke the rule, the rule did not say Broke "
                "(it missed it)."
            )
        if expected == "held" and outcome.verdict == "broke":
            found.append(
                "On a chat where the bot clearly held, the rule said Broke (it flags good "
                "behaviour)."
            )
    return found


CHECK_INTENTION = "Says what counts as a break"
CHECK_RULE = "The rule can be trusted"
CHECK_NORMAL = "Normal use is never flagged"
CHECK_SAMPLES = "The rule gets both sample chats right"
CHECK_MEANING = "The intention agrees with the sample chats"


def check_spec(spec: TestSpec) -> list[tuple[str, str]]:
    """Every problem with this test's rule and intention, as (the check that failed, the evidence)
    in plain words."""
    found: list[tuple[str, str]] = []
    if not (spec.intention or "").strip():
        found.append(
            (CHECK_INTENTION, "The rule has no intention: it does not say what counts as a break.")
        )
    found += [(CHECK_RULE, why) for why in rule_problems(spec)]
    found += [(CHECK_NORMAL, why) for why in real_user_problems(spec)]
    if not found:
        found += [(CHECK_SAMPLES, why) for why in sample_problems(spec)]
    return found
