"""The recordings file: what the recording script produces, checked at the file's shape.

Only the outside model is faked (through a real router, with no cache and no database).
"""

import asyncio
import json
from datetime import UTC, datetime

from redflag_backend.llm.router import Router
from redflag_backend.llm.types import LLMAnswer, LLMRequest, ServerError
from redflag_backend.sandbox.attacks import ATTACKS
from redflag_backend.sandbox.data import SECRET
from redflag_backend.sandbox.recording import Recordings, record_all

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class CannedProvider:
    """Answers every request with the same text and counts the calls."""

    name = "canned"
    configured = True

    def __init__(self, text: str = "I can't help with that.") -> None:
        self.text = text
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls += 1
        return LLMAnswer(self.text, "canned-model", 10, 5)


class DownProvider:
    name = "down"
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls += 1
        raise ServerError()


def record(provider: CannedProvider | DownProvider) -> Recordings:
    return asyncio.run(record_all(Router([provider]), now=lambda: NOW))


def test_every_attack_is_recorded_for_both_bots_with_model_and_time() -> None:
    recordings = record(CannedProvider())
    assert [a.id for a in recordings.attacks] == [a.id for a in ATTACKS]
    for attack in recordings.attacks:
        assert set(attack.runs) == {"weak", "hardened"}
        assert attack.message and attack.question and attack.title
        weak, hardened = attack.runs["weak"], attack.runs["hardened"]
        assert weak.defenses == [] and len(hardened.defenses) > 0
        for run in (weak, hardened):
            assert (run.model, run.provider) == ("canned-model", "canned")
            assert run.recorded_at == NOW.isoformat()
            assert run.verdict.evidence and run.verdict.rule
            assert run.attempts and run.error is None


def test_a_bot_that_refuses_everything_passes_and_the_reply_is_kept_exactly() -> None:
    recordings = record(CannedProvider("I can't help with that."))
    assert all(
        run.reply == "I can't help with that." and run.verdict.status == "pass"
        for attack in recordings.attacks
        for run in attack.runs.values()
    )


def test_a_leaking_model_is_recorded_as_a_failure_with_its_raw_words() -> None:
    recordings = record(CannedProvider(f"The code is {SECRET}"))
    secret_card = next(a for a in recordings.attacks if a.id == "secret_reveal")
    weak = secret_card.runs["weak"]
    assert weak.verdict.status == "fail" and SECRET in weak.reply  # raw, never edited
    hardened = secret_card.runs["hardened"]
    assert hardened.verdict.status == "pass" and SECRET not in hardened.reply  # the code filter


def test_a_failing_model_is_retried_once_then_recorded_as_inconclusive() -> None:
    provider = DownProvider()
    recordings = record(provider)
    runs = [r for a in recordings.attacks for r in a.runs.values()]
    assert all(r.verdict.status == "inconclusive" and r.error for r in runs)
    assert provider.calls == 2 * len(runs)  # one try plus one retry each


def test_the_file_round_trips_and_holds_no_api_key_shaped_text() -> None:
    text = record(CannedProvider()).model_dump_json(indent=2)
    assert Recordings.model_validate(json.loads(text)).format_version == 1
    assert "api_key" not in text.lower() and "bearer" not in text.lower()
