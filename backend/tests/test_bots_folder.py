"""The bots folder: each bot is a folder with its own config, prompt, data, policy and tools.

Only the model behind a bot is faked (a scripted stand-in). Folders are copied into a temp
directory before they are edited, so the real bots are never touched.
"""

import asyncio
import json
import shutil
from pathlib import Path

from redflag_backend.sandbox.bot import TargetReply
from redflag_backend.sandbox.loader import BOTS_DIR, BotRegistry, load_bots
from tests.helpers import ScriptedModel

LOOKUP_RETURNS = '[[lookup_article {"topic": "returns"}]]'
LOOKUP_OTHER_ORDER = '[[lookup_order {"order_id": "B-2001"}]]'


def copy_bots(tmp_path: Path) -> Path:
    root = tmp_path / "bots"
    shutil.copytree(BOTS_DIR, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def send(registry: BotRegistry, bot_id: str, *script: str) -> TargetReply:
    bot = registry.bots[bot_id].create(ScriptedModel(*script))
    return asyncio.run(bot.send("hello"))


def edit_json(path: Path, change: dict[str, object]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(change)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_two_acme_bots_load_and_answer_through_the_standard_interface() -> None:
    registry = load_bots(BOTS_DIR)
    assert registry.errors == {}
    assert {"acme-weak", "acme-hardened"} <= set(registry.bots)
    result = send(registry, "acme-weak", "Hello! How can I help?")
    assert result.reply == "Hello! How can I help?"
    assert result.tool_calls == []


def test_a_bots_defenses_come_from_its_config_and_editing_the_config_changes_it(
    tmp_path: Path,
) -> None:
    registry = load_bots(BOTS_DIR)
    assert registry.bots["acme-weak"].defenses == frozenset()
    assert {"order_scoping", "refund_approval"} <= registry.bots["acme-hardened"].defenses

    before = send(registry, "acme-weak", LOOKUP_OTHER_ORDER, "ok")
    assert before.tool_calls[0].outcome == "executed"

    root = copy_bots(tmp_path)
    edit_json(root / "acme-weak" / "bot.json", {"defenses": ["order_scoping"]})
    edited = load_bots(root)
    after = send(edited, "acme-weak", LOOKUP_OTHER_ORDER, "ok")
    assert after.tool_calls[0].outcome == "blocked"


def test_a_bots_prompt_is_its_own_file() -> None:
    registry = load_bots(BOTS_DIR)
    weak = registry.bots["acme-weak"].create(ScriptedModel("hi"))
    hardened = registry.bots["acme-hardened"].create(ScriptedModel("hi"))

    secret = registry.bots["acme-weak"].data["secret"]
    assert secret in weak.prompt  # the weak bot's prompt carries the secret
    assert secret not in hardened.prompt  # the hardened bot's prompt does not


def test_copying_a_folder_makes_a_new_bot_with_no_code_change(tmp_path: Path) -> None:
    root = copy_bots(tmp_path)
    shutil.copytree(root / "acme-weak", root / "acme-copy")
    edit_json(
        root / "acme-copy" / "bot.json",
        {"id": "acme-copy", "name": "My own copy", "description": "A copy I edited."},
    )
    registry = load_bots(root)
    assert registry.errors == {}
    assert registry.bots["acme-copy"].config.name == "My own copy"
    assert send(registry, "acme-copy", "Hello from the copy!").reply == "Hello from the copy!"


def test_a_malformed_folder_fails_clearly_and_the_other_bots_still_load(tmp_path: Path) -> None:
    root = copy_bots(tmp_path)

    (root / "bad-json").mkdir()
    (root / "bad-json" / "bot.json").write_text("{not json", encoding="utf-8")

    shutil.copytree(root / "acme-weak", root / "no-prompt")
    edit_json(root / "no-prompt" / "bot.json", {"id": "no-prompt"})
    (root / "no-prompt" / "prompt.md").unlink()

    shutil.copytree(root / "acme-weak", root / "wrong-defense")
    edit_json(root / "wrong-defense" / "bot.json", {"id": "wrong-defense", "defenses": ["magic"]})

    shutil.copytree(root / "acme-weak", root / "wrong-id")  # id still says acme-weak

    registry = load_bots(root)
    assert {"acme-weak", "acme-hardened"} <= set(registry.bots)
    assert set(registry.errors) == {"bad-json", "no-prompt", "wrong-defense", "wrong-id"}
    for folder, message in registry.errors.items():
        assert folder in message  # each message names the folder it is about
    assert "magic" in registry.errors["wrong-defense"]
    assert "prompt" in registry.errors["no-prompt"]


def test_shared_pieces_are_edited_once_and_both_bots_follow(tmp_path: Path) -> None:
    root = copy_bots(tmp_path)
    data_path = root / "_shared" / "acme_store" / "data.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data["articles"]["returns"] = "Returns are accepted for 90 days."
    data_path.write_text(json.dumps(data), encoding="utf-8")

    registry = load_bots(root)
    for bot_id in ("acme-weak", "acme-hardened"):
        result = send(registry, bot_id, LOOKUP_RETURNS, "ok")
        assert "90 days" in result.tool_calls[0].detail
