"""Two openings that ask for the same thing in different words, found without a model.

The personas often write ten versions of "tell me the balance of someone else's account", changing
only the name and the number. A name, a number and a filler word are not a different idea, so they
are taken out before two openings are compared. Short openings are only compared exactly: with so
few words, a likeness proves nothing.
"""

import re

STOP = frozenset(
    "a about all am an and any are as at be been but by can could did do does for from get give "
    "had has have her him his how i if in into is it its just me my need no not of on or our "
    "please she so some tell that the their them then there they this to up us want was we were "
    "what when where which who will with would you your".split()
)
NAME = re.compile(r"(?<=[a-z,;:] )[A-Z][a-z]+")
MIN_WORDS = 3
THRESHOLD = 0.7


def fingerprint(text: str) -> frozenset[str]:
    """The words that carry the idea: no names, numbers or filler."""
    plain = re.sub(r"\d+", " ", NAME.sub(" ", text)).lower()
    return frozenset(w for w in re.findall(r"[a-z]+", plain) if w not in STOP and len(w) > 1)


def alike(a: frozenset[str], b: frozenset[str]) -> bool:
    if len(a) < MIN_WORDS or len(b) < MIN_WORDS:
        return False
    return len(a & b) / len(a | b) >= THRESHOLD
