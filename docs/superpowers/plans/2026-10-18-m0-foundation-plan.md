# M0 build plan

Design: `docs/superpowers/specs/2026-10-18-m0-foundation-design.md`. Spec: GitHub issue #1.
Method: test-first for backend `/health` and the frontend status page (the two agreed seams). Commit after each phase.

## Phase 1: Local tooling (no accounts)
- Install `pnpm` and `uv`. Confirm Node 24, Docker and git work.
- Add `.gitignore` (env files, build output, caches) and a root `.editorconfig`.
- Check: `uv --version`, `pnpm --version`.

## Phase 2: Backend skeleton, test-first
- `backend/`: `uv` project pinned to Python 3.12, FastAPI, Pydantic settings, SQLAlchemy, Alembic, pytest, ruff, mypy.
- Local Postgres through Docker Compose, used by tests and local runs.
- Red-green cycles, one behavior at a time, through the HTTP seam:
  1. `/health` returns 200 and `database: ok` with a working database.
  2. `/health` returns 503 and `degraded` when the database is unreachable.
  3. Response carries version, commit (when set) and timestamp, and never contains secrets or stack traces.
  4. Only the configured frontend origin passes CORS.
  5. Startup fails fast if `DATABASE_URL` is missing.
- Alembic configured with an empty baseline migration.
- Dockerfile for the backend. Check: image builds, container serves `/health` against local Postgres.
- Check: ruff, mypy and pytest all pass.

## Phase 3: Frontend skeleton, test-first
- `frontend/`: Next.js + TypeScript + Tailwind + shadcn/ui, `pnpm`, Vitest.
- Red-green cycles through the rendered-page seam, network faked:
  1. Waking-up state with elapsed seconds and automatic retry.
  2. Healthy state shows database status, version and commit.
  3. Unreachable and degraded states show plain-language errors.
- Accessible contrast and text labels for status (no color-only meaning).
- Check: lint, typecheck, Vitest and production build pass; page works against the local backend.

## Phase 4: CI and secret checks
- GitHub Actions: backend job (ruff, mypy, pytest with a Postgres service container), frontend job (lint, typecheck, Vitest, build), gitleaks job.
- Bundle check script that fails on a database connection-string pattern in the built frontend. Prove it once by failing on a planted string.
- Check: CI green on push; planted-secret run fails as expected, then is removed.

## Phase 5: Docs
- `.env.example` for each app (names only).
- README: what Redflag is, architecture sketch, local setup, deploy steps, free-tier facts with date.

## Phase 6: Deploy (owner clicks, builder guides)
Order matters because each side needs the other's URL.
1. Neon: owner creates project; `DATABASE_URL` goes into Render settings only.
2. Render: backend from Dockerfile; migration runs on deploy; check `/health` shows `database: ok`.
3. Vercel: frontend; set `NEXT_PUBLIC_API_URL` to the Render URL.
4. Render: set the allowed origin to the Vercel URL; redeploy.
5. Decide whether Render deploys only after CI passes.

## Phase 7: Acceptance (owner)
Check the live site against the done-when list in the spec. Do not start M1 until the owner approves.

## Risks to watch
- Render cold start (about a minute) can make the first check look broken. The waking-up state is the mitigation.
- Python 3.12 via `uv` may need a download. Python 3.14 must not be used for the backend.
- Neon wakes in seconds after 5 idle minutes. The database check timeout must allow for that.
- Free-tier limits may have changed since 2026-10-18. Recheck at deploy time.
