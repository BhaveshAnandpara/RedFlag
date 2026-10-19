"""What the owner tells Redflag about a bot: the fields, the endpoint and the connection state.

The endpoint key is never part of any of this. It is typed into a secure field, used for one
call and dropped.
"""

from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["user", "model", "edited"]
Severity = Literal["critical", "high", "medium"]
RuleKind = Literal["allowed", "forbidden"]
# stated: the user said it or confirmed it. inferred: the model guessed it. unclear: not settled.
RuleStatus = Literal["stated", "inferred", "unclear"]

MAX_CONNECTION_TESTS = 5


class FieldValue(BaseModel):
    value: str = ""
    source: Source = "model"
    locked: bool = False


class Rule(BaseModel):
    id: str
    text: str
    kind: RuleKind
    severity: Severity = "high"
    status: RuleStatus = "stated"
    # The question that would clear an unclear rule
    question: str | None = None
    source: Source = "user"
    locked: bool = False


class Fields(BaseModel):
    purpose: FieldValue = Field(default_factory=FieldValue)
    rules: list[Rule] = Field(default_factory=list)
    notes: FieldValue = Field(default_factory=FieldValue)


class Endpoint(BaseModel):
    url: str = ""
    format: Literal["openai", "custom"] = "openai"
    model: str = "default"
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "
    request_template: str | None = None
    reply_path: str | None = None


class Connection(BaseModel):
    ok: bool = False
    attempts: int = 0
    last_error: str | None = None


class SetupData(BaseModel):
    fields: Fields = Field(default_factory=Fields)
    endpoint: Endpoint = Field(default_factory=Endpoint)
    connection: Connection = Field(default_factory=Connection)


def required_status(data: SetupData) -> dict[str, bool]:
    """The items that must be filled before the rules can be reviewed.

    A rule only counts if the user stated it or confirmed it: one the model merely inferred, or
    one marked unclear, does not.
    """
    status = {
        "connection": data.connection.ok,
        "purpose": bool(data.fields.purpose.value.strip()),
        "forbidden_rule": any(
            rule.kind == "forbidden" and rule.status == "stated" and rule.text.strip()
            for rule in data.fields.rules
        ),
    }
    return {**status, "ready": all(status.values())}
