"""The versioned catalog of risks that tests are mapped to."""

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CATALOG_PATH = Path(__file__).with_name("data") / "owasp-llm-2025.json"


@dataclass(frozen=True)
class Risk:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class Catalog:
    version: str
    name: str
    source: str
    retrieved: str
    risks: tuple[Risk, ...]

    def risk(self, risk_id: str) -> Risk | None:
        return next((r for r in self.risks if r.id == risk_id), None)


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Catalog(
        version=raw["version"],
        name=raw["name"],
        source=raw["source"],
        retrieved=raw["retrieved"],
        risks=tuple(Risk(r["id"], r["name"], r["description"]) for r in raw["risks"]),
    )
