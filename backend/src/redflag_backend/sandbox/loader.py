"""Load bots from the bots folder.

A bot is a folder holding bot.json (its config), prompt.md, data.json, policy.json and
tools.py. Any of the last four may instead live in a shared folder (bots/_shared/<name>) that
several bots use, so a common piece is edited once. A folder that cannot be loaded is reported
with a clear message and does not stop the other bots from loading.
"""

import importlib.util
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from redflag_backend.sandbox.bot import ALL_DEFENSES, Bot, Model
from redflag_backend.sandbox.paths import BOTS_DIR, SHARED_DIR_NAME
from redflag_backend.sandbox.policy import Policy, PolicyError, load_policy
from redflag_backend.sandbox.tools import ToolBox

__all__ = ["BOTS_DIR", "BotConfig", "BotDefinition", "BotLoadError", "BotRegistry", "load_bots"]

ToolHandler = Callable[[ToolBox, dict[str, Any]], str]


class BotLoadError(Exception):
    """A bot folder could not be loaded. The message names the folder."""


class BotConfig(BaseModel):
    # Unknown keys are an error, so a typo in a config is caught instead of silently ignored.
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    shared: str | None = None
    defenses: list[str] = []
    config_version: int = 1


class ToolInfo(BaseModel):
    """What one tool is, in plain words, for whoever reads the tool-call log (the AI judge)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    # "reads" only looks things up; "acts" changes something in the world
    effect: Literal["reads", "acts"]
    description: str


@dataclass(frozen=True)
class BotDefinition:
    folder: Path
    config: BotConfig
    prompt: str
    data: dict[str, Any]
    policy: Policy
    tools: dict[str, ToolHandler]
    # From the optional tools.json: what each tool means. Empty when a bot has no such file.
    tool_info: list[ToolInfo] = field(default_factory=list)

    @property
    def defenses(self) -> frozenset[str]:
        return frozenset(self.config.defenses)

    def create(
        self,
        model: Model,
        defenses: frozenset[str] | None = None,
        secret: str | None = None,
    ) -> Bot:
        """A runnable bot. `defenses` overrides the config's switches (used by tests), and
        `secret` replaces the bot's secret (a scan plants a fresh canary this way)."""
        data = self.data if secret is None else {**self.data, "secret": secret}
        return Bot(
            model=model,
            defenses=self.defenses if defenses is None else defenses,
            prompt=self.prompt,
            data=data,
            policy=self.policy,
            tools=self.tools,
        )


@dataclass
class BotRegistry:
    bots: dict[str, BotDefinition] = field(default_factory=dict)
    # folder name -> message, for every folder that could not be loaded
    errors: dict[str, str] = field(default_factory=dict)


def load_bots(root: Path = BOTS_DIR) -> BotRegistry:
    registry = BotRegistry()
    if not root.is_dir():
        return registry
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder.name.startswith(("_", ".")) or folder.name == "__pycache__":
            continue
        try:
            definition = _load_folder(root, folder)
        except BotLoadError as error:
            registry.errors[folder.name] = str(error)
            continue
        registry.bots[definition.config.id] = definition
    return registry


def _fail(folder: Path, message: str) -> BotLoadError:
    return BotLoadError(f"{folder.name}: {message}")


def _load_folder(root: Path, folder: Path) -> BotDefinition:
    config = _read_config(folder)
    search = [folder]
    if config.shared:
        shared = root / SHARED_DIR_NAME / config.shared
        if not shared.is_dir():
            raise _fail(folder, f"the shared folder '{config.shared}' does not exist")
        search.append(shared)

    def find(name: str) -> Path:
        for directory in search:
            if (directory / name).is_file():
                return directory / name
        raise _fail(
            folder, f"{name} was not found (looked in the bot folder and its shared folder)"
        )

    try:
        prompt = find("prompt.md").read_text(encoding="utf-8")
        data = _read_json(folder, find("data.json"))
        policy = load_policy(find("policy.json"))
    except PolicyError as error:
        raise _fail(folder, str(error)) from error
    return BotDefinition(
        folder=folder,
        config=config,
        prompt=prompt,
        data=data,
        policy=policy,
        tools=_load_tools(folder, find("tools.py")),
        tool_info=_load_tool_info(folder, search),
    )


def _read_json(folder: Path, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise _fail(folder, f"{path.name} could not be read as JSON: {error}") from error
    if not isinstance(value, dict):
        raise _fail(folder, f"{path.name} must hold a JSON object")
    return value


def _read_config(folder: Path) -> BotConfig:
    path = folder / "bot.json"
    if not path.is_file():
        raise _fail(folder, "bot.json was not found")
    raw = _read_json(folder, path)
    try:
        config = BotConfig.model_validate(raw)
    except ValidationError as error:
        raise _fail(folder, f"bot.json is not valid: {error}") from error
    if config.id != folder.name:
        raise _fail(
            folder, f"bot.json says id '{config.id}' but the folder is called '{folder.name}'"
        )
    unknown = sorted(set(config.defenses) - ALL_DEFENSES)
    if unknown:
        raise _fail(
            folder,
            f"unknown defense(s) {unknown}; known defenses are {sorted(ALL_DEFENSES)}",
        )
    return config


def _load_tool_info(folder: Path, search: list[Path]) -> list[ToolInfo]:
    for directory in search:
        path = directory / "tools.json"
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("it must hold a list of tools")
            return [ToolInfo.model_validate(item) for item in raw]
        except (OSError, ValueError) as error:  # a ValidationError is a ValueError
            raise _fail(folder, f"tools.json is not valid: {error}") from error
    return []


def _load_tools(folder: Path, path: Path) -> dict[str, ToolHandler]:
    spec = importlib.util.spec_from_file_location(f"redflag_bot_tools_{folder.name}", path)
    if spec is None or spec.loader is None:
        raise _fail(folder, f"{path.name} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # the owner's own code: report it, never crash the loader
        raise _fail(folder, f"{path.name} failed to load: {error!r}") from error
    tools = getattr(module, "TOOLS", None)
    if not isinstance(tools, dict) or not all(callable(fn) for fn in tools.values()):
        raise _fail(folder, f"{path.name} must define TOOLS, a dict of tool name to function")
    return dict(tools)
