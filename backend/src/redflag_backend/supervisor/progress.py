"""What the page shows while a plan is being made: a headline, a short feed of what just
happened, and a countdown when the models' quota has run out and we are waiting to try again.

It only records. The plan job keeps one of these and the page asks for its snapshot, so the
user sees what is going on instead of a spinner that says nothing.
"""

from collections.abc import Callable
from typing import Any

from redflag_backend.setups.llm import Patience

FEED_LINES = 8

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
        self.feed: list[str] = []
        self.goal_index = 0
        self.goal_total = 0
        self._wait_until: float | None = None
        self.patience = Patience(wait_seconds, max_waits, self._waiting, self._resumed)

    def say(self, text: str) -> None:
        self.feed.append(text)
        del self.feed[:-FEED_LINES]

    def working_on(self, headline: str) -> None:
        self.headline = headline

    def goal(self, index: int, total: int, question: str) -> None:
        self.goal_index, self.goal_total = index, total
        self.headline = f"Goal {index} of {total}: {question}"

    def asking(self, persona_ids: list[str], retry_round: int = 0) -> None:
        names = [ASKING[p] for p in persona_ids]
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        text = f"Asking {who}"
        if retry_round:
            text += f", for different angles (try {retry_round} of 3)"
        self.say(text + "…")

    def snapshot(self) -> dict[str, Any]:
        left = 0.0 if self._wait_until is None else max(0.0, self._wait_until - self._clock())
        return {
            "headline": self.headline,
            "feed": list(self.feed),
            "goal_index": self.goal_index,
            "goal_total": self.goal_total,
            "waiting": left > 0,
            "seconds_left": round(left),
        }

    def _waiting(self, seconds: float, attempt: int, of: int) -> None:
        now = self._clock()
        if self._wait_until is not None and self._wait_until > now:
            return  # several personas hit the quota together: one wait, one line
        self._wait_until = now + seconds
        self.say(
            f"The AI models' quota for this minute is used up. Waiting {_span(seconds)}, "
            f"then trying again (wait {attempt} of {of})."
        )

    def _resumed(self) -> None:
        if self._wait_until is not None and self._clock() >= self._wait_until - 0.001:
            self._wait_until = None
            self.say("Trying again…")
