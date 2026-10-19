"""Where the bots live. In the container the backend sits in /app, so this is /app/bots."""

from pathlib import Path

BOTS_DIR = Path(__file__).resolve().parents[3] / "bots"
SHARED_DIR_NAME = "_shared"
ACME_SHARED = BOTS_DIR / SHARED_DIR_NAME / "acme_store"
