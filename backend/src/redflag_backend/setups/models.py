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


class Item(BaseModel):
    """A short fact such as a limit or a kind of protected data."""

    id: str
    text: str
    source: Source = "model"
    locked: bool = False


class ToolSpec(BaseModel):
    name: str
    description: str
    # "reads" only looks things up; "acts" changes something in the world
    effect: Literal["reads", "acts"] = "acts"
    source: Source = "model"
    locked: bool = False


class Example(BaseModel):
    """Something the user pasted, kept word for word. Only the user adds these, never a model."""

    id: str
    text: str
    label: Literal["bad_reply", "good_reply", "conversation"] = "conversation"


class Fields(BaseModel):
    purpose: FieldValue = Field(default_factory=FieldValue)
    rules: list[Rule] = Field(default_factory=list)
    limits: list[Item] = Field(default_factory=list)
    protected_data: list[Item] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    notes: FieldValue = Field(default_factory=FieldValue)
    # Topics the user chose not to answer. They stay unclear and are never guessed.
    unclear: list[str] = Field(default_factory=list)


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


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class UploadedFile(BaseModel):
    name: str
    content: str


class Tagged(BaseModel):
    """One line of a context, with where it came from."""

    text: str
    source: Literal["user", "model"] = "model"


class TesterContext(BaseModel):
    purpose: str = ""
    tools: list[ToolSpec] = Field(default_factory=list)
    weak_spots: list[Tagged] = Field(default_factory=list)
    what_to_try: list[Tagged] = Field(default_factory=list)
    notes: str = ""


class JudgeContext(BaseModel):
    purpose: str = ""
    rules: list[Tagged] = Field(default_factory=list)
    limits: list[Tagged] = Field(default_factory=list)
    protected_data: list[Tagged] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)
    # Always the user's own examples, word for word, never written by a model
    examples: list[Example] = Field(default_factory=list)
    unclear: list[str] = Field(default_factory=list)
    notes: str = ""


class Contexts(BaseModel):
    tester: TesterContext = Field(default_factory=TesterContext)
    judge: JudgeContext = Field(default_factory=JudgeContext)
    # Context fields the user edited, as "tester.notes" or "judge.rules". Regenerating keeps them.
    locked: list[str] = Field(default_factory=list)


class SetupData(BaseModel):
    fields: Fields = Field(default_factory=Fields)
    endpoint: Endpoint = Field(default_factory=Endpoint)
    connection: Connection = Field(default_factory=Connection)
    chat: list[ChatTurn] = Field(default_factory=list)
    files: list[UploadedFile] = Field(default_factory=list)
    contexts: Contexts | None = None
    followups_asked: int = 0
    user_messages: int = 0


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
