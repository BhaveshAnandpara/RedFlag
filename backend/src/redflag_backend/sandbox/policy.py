"""The shop's rules in a form the program can read.

Both the bot's code defenses and the verdict checks read this one file, so they cannot drift
apart. It is hand-written for now; M6 turns plain-language rules into this shape.
"""

import json
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ValidationError

DEFAULT_POLICY_PATH = Path(__file__).with_name("policy.json")


class PolicyError(Exception):
    """The policy file is missing, unreadable or the wrong shape."""


class Policy(BaseModel):
    name: str = ""
    # Rule texts, cited in each verdict.
    rules: dict[str, str]
    # Fields of another customer's order that must never appear in a reply.
    protected_order_fields: list[str]
    refund_limit: float
    allowed_email_recipients: list[str]


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> Policy:
    try:
        return Policy.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as error:
        # ValidationError is a ValueError; the message says what is wrong without leaking data.
        raise PolicyError(f"The policy file {path.name} could not be used: {error}") from error


@cache
def default_policy() -> Policy:
    return load_policy()
