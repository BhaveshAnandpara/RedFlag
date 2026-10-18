"""Make the recordings the explainer page shows.

Run from the backend folder:  uv run python -m redflag_backend.sandbox.record
It reads the provider keys from the git-ignored .env.local, asks the real models, and writes
frontend/src/data/recordings.json. Nothing is cached, so every recording is a fresh run.
"""

import argparse
import asyncio
import os
from pathlib import Path

from redflag_backend.llm.providers.factory import build_providers
from redflag_backend.llm.router import Router
from redflag_backend.sandbox.recording import Recordings, record_all
from redflag_backend.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV = REPO_ROOT / ".env.local"
DEFAULT_OUT = REPO_ROOT / "frontend" / "src" / "data" / "recordings.json"


def summarize(recordings: Recordings) -> str:
    lines = []
    for attack in recordings.attacks:
        for name, run in attack.runs.items():
            via = f"{run.provider}/{run.model}" if run.model else "no answer"
            lines.append(f"{attack.id:20} {name:9} {run.verdict.status:13} {via}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--providers",
        help="comma-separated provider names to use, in the router order (default: all)",
    )
    args = parser.parse_args()

    # The router needs no database here (no cache), but Settings insists on these two.
    os.environ.setdefault("DATABASE_URL", "postgresql://unused/unused")
    os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")
    settings = Settings(_env_file=args.env_file)
    providers = build_providers(settings)
    if args.providers:
        wanted = {name.strip() for name in args.providers.split(",")}
        providers = [p for p in providers if p.name in wanted]
    print("Providers with a key:", [p.name for p in providers if p.configured] or "none")

    recordings = asyncio.run(record_all(Router(providers)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(recordings.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(summarize(recordings))
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
