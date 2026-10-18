# M0: Foundation and first deploy: design

Status: draft for approval. Date: 2026-10-18.

## Intent and why

Redflag is a final security check that AI developers run before releasing an LLM app (see `docs/Redflag_Milestones.md`). Milestones are built one at a time. Each ends with a live deployment that the owner checks before the next begins.

M0 proves the whole free hosting path works before any feature sits on top of it: a public frontend, a deployed backend, a real database connection, CI on every push, and no secrets leaking. The product does nothing yet. The deliverable is a deployed skeleton that is honest about its own health.

Spec items covered: NFR-18 (deployment, health checks, CI), NFR-01 (secrets).

## Goals

- A public URL serves the frontend. It shows a live result from the deployed backend's `/health`.
- The backend's `/health` reports whether the database connection actually works.
- CI runs on every push and checks lint, types, tests and secret scanning for both halves.
- No secret appears in the repo or in the client bundle.
- One repo, `frontend/`, `backend/` and `docs/`, reproducible from the README.

## Non-goals

No auth or accounts, no product features, no LLM provider keys or calls (that is M1), no pgvector, no Playwright end-to-end tests, no custom domain, no rate limiting, no keep-warm pinger.

## Anti-goals (a failure even if it technically works)

- `/health` returning "healthy" while the database is unreachable.
- A secret in git history, the repo, or the browser bundle.
- A frontend that looks broken while the backend wakes up from sleep.
- Unrequested features creeping in "since we're here".

## Decided by the owner

- Build order is the milestone doc's: one milestone at a time, deployed and checked before the next.
- Tech stack as in the owner's "Redflag tech stack" note: Next.js + TypeScript + Tailwind + shadcn/ui on the frontend; Python + FastAPI + Pydantic + httpx, SQLAlchemy + Alembic, Postgres on Neon, `uv`, `pnpm`, `ruff`, `mypy`, pytest, Vitest, GitHub Actions on the tooling side.
- Backend host: **Render** free web service. Hugging Face Spaces is out, because Docker Spaces now require a paid plan (checked 2026-10-18).
- The frontend shows a loading state while the backend wakes.
- The owner creates the GitHub repo, and creates the Neon, Vercel and Render accounts as each step needs them.

## Free-tier facts (checked 2026-10-18; recheck before launch)

| Service | What matters for M0 |
|---|---|
| Render free web service | Sleeps after 15 min idle; wakes in about 1 min; 750 free hours/month; filesystem wiped on restart |
| Neon free | 0.5 GB storage; 100 compute-hours/month; suspends after 5 min idle; wakes in seconds |
| Vercel Hobby | Free, non-commercial use only; quotas vary by source |

## Design

### Repo layout

```
frontend/   Next.js app
backend/    FastAPI app, Alembic migrations, tests, Dockerfile
docs/       specs and milestone docs
.github/workflows/
README.md   setup, architecture sketch, deploy steps
.env.example (per app, names only, no values)
```

### Backend

- `GET /health` returns JSON: overall `status` (`ok` or `degraded`), `database` (`ok` or `error`), app `version`, `commit` (from the deploy environment when present) and a server timestamp.
- The database check runs a real query (`SELECT 1`) against Neon with a short timeout. When it fails, `/health` returns HTTP 503 with `status: degraded`, never 200.
- No secrets, connection strings or stack traces appear in the response or logs.
- CORS allows only the configured frontend origin.
- Configuration is read from environment variables through a Pydantic settings class. `DATABASE_URL` is required and set only in Render's environment settings.
- Alembic is set up with an empty baseline migration that runs on deploy. This proves the migration path now. No product tables yet.
- Deployed to Render from the repo's Dockerfile (owner's stack lists Docker; this also matches local runs).

### Frontend

- One page calls the backend `/health` and shows one of three states: **waking up** (with elapsed seconds, retrying, since a cold start takes about a minute), **healthy** (shows database status, version, commit) or **unreachable/degraded** (plain-language error).
- The backend URL comes from `NEXT_PUBLIC_API_URL`. That value is public by design and holds no secret.
- Deployed to Vercel from the repo.

### CI (GitHub Actions, every push)

- Backend: `ruff`, `mypy`, `pytest`.
- Frontend: lint, typecheck, Vitest, production build.
- `gitleaks` on the repo.
- A bundle check that fails if the built frontend contains a database connection-string pattern.
- Deploys use each host's Git integration from `main`. CI is a separate gate, and the builder decides whether Render deploys only after checks pass.

### Tests

- Backend: `/health` returns 200 with a working database and 503 when the database fails (unit, database mocked), plus one integration test against a real Postgres service container in CI.
- Frontend: Vitest covers the three page states with a mocked fetch.

### Secrets handling

- `.env` files are git-ignored. `.env.example` lists names only.
- Real values live only in Render and Vercel settings.
- `gitleaks` and the bundle check enforce this in CI.

## Done when (from the milestone doc)

1. A public URL loads the frontend, which shows a healthy response from the deployed backend.
2. The database connection works from the backend (`/health` reports `database: ok`).
3. CI runs on every push.
4. No secret appears in the repo or the client bundle.

## Owner actions during the build

Create the GitHub repo and push; create Neon, Render and Vercel accounts and projects when asked; paste `DATABASE_URL`, the frontend origin and `NEXT_PUBLIC_API_URL` into the hosts' settings. The builder says exactly what to click at each point.

## Calls made without the owner (change any of these)

- **Public GitHub repo.** This is a portfolio project, so public is natural, but it makes the secret checks matter more. Private also works.
- **Python 3.12 pinned through `uv`**, because the installed Python 3.14 is new and some libraries lag. Node 24 is already installed.
- **Neon over Supabase**, because the demo needs no accounts and Supabase pauses inactive projects.
- **Empty baseline Alembic migration** and no tables in M0.
- **Dockerfile deploy on Render** rather than Render's native Python build.
- **No keep-warm pinger.** The loading state is the answer to cold starts.
- **Playwright end-to-end tests wait** until there is a real user flow to test.
- **`pnpm`, `uv` and the GitHub CLI are not installed on the owner's machine yet.** The builder installs `pnpm` and `uv`. The GitHub CLI is optional.

## Left to the builder

Exact versions, folder internals, lint rules, the look of the status page (simple and readable, accessible contrast per NFR-16), CI job layout, and whether Render deploys only after CI passes.
