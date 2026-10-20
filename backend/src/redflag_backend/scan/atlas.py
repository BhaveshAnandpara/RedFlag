"""MITRE ATLAS tags for the OWASP risks: Redflag's own best match, with its source and date."""

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("data") / "atlas-mapping.json"


@dataclass(frozen=True)
class Technique:
    id: str
    name: str


@dataclass(frozen=True)
class AtlasMapping:
    source: str
    version: str
    checked: str
    note: str
    by_risk: dict[str, list[Technique]]

    def tags(self, risk_id: str) -> list[dict[str, str]]:
        return [{"id": t.id, "name": t.name} for t in self.by_risk.get(risk_id, [])]

    def meta(self) -> dict[str, str]:
        return {
            "source": self.source,
            "version": self.version,
            "checked": self.checked,
            "note": self.note,
        }


def load_atlas(path: Path = DEFAULT_PATH) -> AtlasMapping:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AtlasMapping(
        source=raw["source"],
        version=raw["version"],
        checked=raw["checked"],
        note=raw["note"],
        by_risk={
            risk: [Technique(t["id"], t["name"]) for t in techniques]
            for risk, techniques in raw["map"].items()
        },
    )


ATLAS = load_atlas()
