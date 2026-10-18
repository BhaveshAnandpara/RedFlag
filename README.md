# Redflag

Redflag is an AI application security assessment platform. It tests whether LLM apps, RAG systems, agents and MCP tools obey their intended rules, and it shows evidence for every finding.

The goal is a final security check developers run before releasing an AI app. It never claims an app is completely secure: every report must separate what was tested from what was not.

**Status: Milestone 0 (foundation).** The app currently does one thing: a status page that shows whether the deployed backend and its database are healthy. Product features arrive milestone by milestone. See [docs/Redflag_Milestones.md](docs/Redflag_Milestones.md).

## How it fits together

```
Browser ──► Frontend (Next.js, Vercel) ──► Backend (FastAPI, Render) ──► Postgres (Neon)
                  GET /health  ◄────────── status, database, version, commit
```

- `frontend/`: Next.js, TypeScript and Tailwind. One status page that calls the backend's `/health`.
- `backend/`: FastAPI, SQLAlchemy and Alembic. `/health` runs a real database query and returns 503 with `degraded` when the database is unreachable.
- `docs/`: requirements, milestone plan, and per-milestone designs, specs and plans.

Free hosts sleep when idle (Render after 15 minutes, Neon after 5), so the first visit can take about a minute. The status page shows a "waking up" message and retries on its own.

## Run it locally

You need Docker Desktop, [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/).

```bash
# 1. Database
docker compose up -d --wait db

# 2. Backend (http://localhost:8000/health)
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn redflag_backend.main:app --reload

# 3. Frontend (http://localhost:3000), in a second terminal
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

## Tests and checks

```bash
# Backend (needs the database from step 1)
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest

# Frontend
cd frontend
pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm check:bundle
```

CI runs all of this on every push, plus a `gitleaks` secret scan. `pnpm check:bundle` fails if a database connection string ends up in the browser bundle.

## Configuration and secrets

| Variable | Where it is set | Secret? |
|---|---|---|
| `DATABASE_URL` | Backend host settings only | Yes. Never commit it |
| `FRONTEND_ORIGIN` | Backend host settings | No |
| `NEXT_PUBLIC_API_URL` | Frontend host settings | No. Public by design |

`.env` files are git-ignored. The `.env.example` files list names only.

## Deploying

Free tiers only. Limits below were checked on 2026-10-18 and change often, so recheck them before relying on them.

| Part | Host | Free-tier facts that matter |
|---|---|---|
| Frontend | Vercel (Hobby) | Free for non-commercial use |
| Backend | Render (free web service, Dockerfile) | Sleeps after 15 min idle, wakes in about a minute, 750 hours a month |
| Database | Neon (free Postgres) | 0.5 GB storage, suspends after 5 min idle, wakes in seconds |

Order matters because each side needs the other's URL: Neon first, then the Render backend, then the Vercel frontend, then add the frontend's URL to the backend's `FRONTEND_ORIGIN`. Hugging Face Spaces is not used because Docker Spaces now require a paid plan.

## Limitations

Milestone 0 has no security testing yet. A "healthy" result only means the backend and database respond. It is not a security claim.
