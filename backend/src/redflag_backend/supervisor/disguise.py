"""Adding disguised copies of the plan's attacks, so one plan covers many techniques.

The personas write plain attacks. For some of them a copy is added that the same attack dressed up
by code (an encoding, a role-play, a fake system message), chosen so that techniques rotate and no
goal gets the same one twice. A copy keeps the original's rule, intention and sample chats: they
are about the bot's reply, which the disguise does not change. No model is called.
"""

from redflag_backend.attacks.disguises import DISGUISES, disguise
from redflag_backend.specs.spec import TestSpec

# One disguised copy for every this many plain attacks of a goal, and never more than the cap.
ONE_IN = 3
MAX_PER_GOAL = 4

# Encodings and framings alternate, so even a goal with a few copies gets a mix.
ORDER = [
    "base64", "roleplay", "rot13", "system_spoof", "leetspeak", "fiction", "lookalike",
    "override", "reversed", "hypothetical", "invisible", "priming", "split", "authority",
    "many_shot", "urgency",
]  # fmt: skip
assert set(ORDER) == set(DISGUISES)


def can_disguise(spec: TestSpec) -> bool:
    """A plain chat attack. Text planted for the bot to read, and tests that are already a
    disguise, are left alone."""
    return (
        spec.kind == "attack"
        and spec.mode == "B"
        and spec.technique is None
        and not spec.setup.planted_text
    )


def copies(specs: list[TestSpec], start: int) -> tuple[list[TestSpec], int]:
    """The disguised copies for one goal's tests, and where the rotation stands afterwards."""
    base = [s for s in specs if can_disguise(s)]
    wanted = min(MAX_PER_GOAL, len(base) // ONE_IN)
    if wanted == 0 and len(base) >= 2:
        wanted = 1
    made: list[TestSpec] = []
    position = start
    used: set[str] = set()
    for i in range(wanted):
        original = base[(i * len(base)) // wanted]
        technique = next(
            (t for k in range(len(ORDER)) if (t := ORDER[(position + k) % len(ORDER)]) not in used),
            None,
        )
        if technique is None:
            break
        position = (ORDER.index(technique) + 1) % len(ORDER)
        used.add(technique)
        label = DISGUISES[technique].name
        made.append(
            original.model_copy(
                update={
                    "opening_message": disguise(technique, original.opening_message),
                    "technique": technique,
                    "strategy": f"{original.strategy or 'attack'} ({label})",
                }
            )
        )
    return made, position
