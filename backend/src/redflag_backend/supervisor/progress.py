"""What the page shows while a plan is being made: an ordered list of things that really happened.

Each step ("asking the fake insider…") and each finished test is added to the list with a number.
The page asks for the next item every few seconds and adds it to its timeline, so the user watches
the plan being written. Nothing here is made up: a line is only added for something that happened,
and the page may show it a little later than it happened.

A wait for the models' quota is also an event, and the snapshot says how long is left so the page
can show a live countdown.
"""

import math
from collections.abc import Callable
from typing import Any

from redflag_backend.setups.llm import Patience

# A big plan must not drag on: more than this many items waiting are handed out several at a time.
CATCH_UP_BEATS = 60

# What each persona is being asked to do, in words a person would use.
ASKING: dict[str, str] = {
    "social_engineer": "the social engineer to write believable, pressuring conversations",
    "fake_insider": "the fake insider to pose as staff",
    "content_poisoner": "the content poisoner to hide instructions inside data",
    "data_harvester": "the data harvester to ask for other people's data",
    "resource_abuser": "the resource abuser to try wasting your bot's resources",
    "qa_tester": "the QA tester for odd but valid input",
    "normal_user": "a normal user for everyday requests",
}


def _span(seconds: float) -> str:
    if seconds == 60:
        return "a minute"
    return f"{round(seconds)} seconds"


class Progress:
    def __init__(
        self,
        clock: Callable[[], float],
        wait_seconds: float,
        max_waits: int,
    ) -> None:
        self._clock = clock
        self._wait_seconds = wait_seconds
        self.headline = "Getting started"
        self.events: list[dict[str, Any]] = []
        self.goal_index = 0
        self.goal_total = 0
        self.tests = 0
        self._wait_until: float | None = None
        self.patience = Patience(wait_seconds, max_waits, self._waiting, self._resumed)

    def _add(self, kind: str, text: str, **more: Any) -> None:
        self.events.append({"seq": len(self.events), "kind": kind, "text": text, **more})

    def say(self, text: str) -> None:
        self._add("status", text)

    def working_on(self, headline: str) -> None:
        self.headline = headline

    def goal(self, index: int, total: int, question: str) -> None:
        self.goal_index, self.goal_total = index, total
        self.headline = f"Goal {index} of {total}: {question}"
        self._add("goal", f"Goal {index} of {total}: {question}")

    def test(
        self,
        persona_id: str,
        persona: str,
        goal: str,
        message: str,
        changes_data: bool,
    ) -> None:
        """A finished test, as a card on the page."""
        self.tests += 1
        self._add(
            "test",
            message,
            persona_id=persona_id,
            persona=persona,
            goal=goal,
            changes_data=changes_data,
        )

    def asking(self, persona_ids: list[str], retry_round: int = 0) -> None:
        names = [ASKING[p] for p in persona_ids]
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        text = f"Asking {who}"
        if retry_round:
            text += f", for different angles (try {retry_round} of 3)"
        self.say(text + "…")

    def next_items(self, after: int) -> tuple[list[dict[str, Any]], int]:
        """The next item after number `after` (or several, when many are waiting), and the number
        to ask from next time."""
        after = max(0, after)
        waiting = len(self.events) - after
        # Set by the size of the whole plan, so it hands out the same number every beat and the
        # whole list is shown in at most CATCH_UP_BEATS beats.
        take = (
            min(waiting, max(1, math.ceil(len(self.events) / CATCH_UP_BEATS))) if waiting > 0 else 0
        )
        items = self.events[after : after + take]
        return items, after + len(items)

    def snapshot(self, after: int = 0) -> dict[str, Any]:
        items, upto = self.next_items(after)
        left = 0.0 if self._wait_until is None else max(0.0, self._wait_until - self._clock())
        return {
            "headline": self.headline,
            "events": items,
            "next": upto,
            "total": len(self.events),
            "tests": self.tests,
            "goal_index": self.goal_index,
            "goal_total": self.goal_total,
            "waiting": left > 0,
            "seconds_left": round(left),
        }

    def drained(self, after: int) -> bool:
        return max(0, after) >= len(self.events)

    def _waiting(self, seconds: float, attempt: int, of: int) -> None:
        now = self._clock()
        if self._wait_until is not None and self._wait_until > now:
            return  # several personas hit the quota together: one wait, one line
        self._wait_until = now + seconds
        self._add(
            "wait",
            f"The AI models' quota for this minute is used up. Waiting {_span(seconds)}, "
            f"then trying again (wait {attempt} of {of}).",
        )

    def _resumed(self) -> None:
        if self._wait_until is not None and self._clock() >= self._wait_until - 0.001:
            self._wait_until = None
            self.say("Trying again…")
