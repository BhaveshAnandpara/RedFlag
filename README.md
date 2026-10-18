# Redflag

**A final security check for AI apps, before you release them.**

Redflag tests whether LLM apps, RAG systems, agents and MCP tools obey their intended rules, and shows the evidence behind every finding. It is built to be honest: it never claims an app is "completely secure", and every report must separate what was **tested** from what was **not tested** or **inconclusive**.

> **Status: Milestone 0 of 11 (foundation) is deployed.**
> The app currently has one page: a status check showing whether the backend and its database are healthy. Security testing arrives in later milestones. See the [roadmap](#roadmap).

- Live backend health check: <https://redflag-8dcv.onrender.com/health>
- Live frontend: _add the Vercel address here_

## Contents

[How it works](#how-it-works) · [Tech stack](#tech-stack) · [Run it locally](#run-it-locally) · [Tests and checks](#tests-and-checks) · [Configuration](#configuration-and-secrets) · [Deploying](#deploying) · [Troubleshooting](#troubleshooting) · [Limitations](#limitations) · [Roadmap](#roadmap) · [Project layout](#project-layout) · [Docs](#documentation)

## How it works

### Architecture

```mermaid
flowchart LR
    user([Browser])
    subgraph vercel[Vercel]
        fe[Frontend<br/>Next.js]
    end
    subgraph render[Render]
        be[Backend<br/>FastAPI in Docker]
    end
    subgraph neon[Neon]
        db[(Postgres)]
    end

    user -->|loads the page| fe
    user -->|GET /health| be
    be -->|SELECT 1| db
```

The browser loads the page from Vercel, then calls the backend directly. For that to work, the backend must list the frontend's address in `FRONTEND_ORIGIN`. That setting is the CORS allow-list.

### A visit when the backend is asleep

The free hosts sleep when idle, so the first visit can hit a sleeping backend. The page is built for it:

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as Backend (Render)
    participant D as Database (Neon)

    B->>A: GET /health
    Note over A: Asleep. Takes about 1 minute to start
    A--xB: no usable reply
    Note over B: "Waking up the backend..." (retries every 3s)
    B->>A: GET /health
    A->>D: SELECT 1
    D-->>A: ok
    A-->>B: 200 healthy
```

### What the status page can show

```mermaid
stateDiagram-v2
    [*] --> Waking
    Waking --> Waking: no usable reply, retry in 3s
    Waking --> Healthy: 200 and status ok
    Waking --> Degraded: reply says database error
    Waking --> Unreachable: no reply after 90s
```

| You see | It means |
|---|---|
| **Waking up the backend…** with a counter | Normal on a first visit. Give it up to about a minute |
| **Backend is healthy** | Backend and database both respond |
| **Backend is running, but its database is not responding** | The backend is up, but its database check failed |
| **Could not reach the backend** | No answer for 90 seconds. See [Troubleshooting](#troubleshooting) |

### The health check

`GET /health` on the backend:

| Situation | HTTP status | Body |
|---|---|---|
| Database query works | `200` | `{"status":"ok","database":"ok","version":"…","commit":"…","timestamp":"…"}` |
| Database unreachable | `503` | same shape, with `"status":"degraded","database":"error"` |

It never includes credentials, connection strings or stack traces.

### Code to deployment

```mermaid
flowchart LR
    push[Push to main] --> ci
    subgraph ci[GitHub Actions CI]
        direction TB
        b[backend: ruff, mypy, pytest]
        f[frontend: lint, typecheck,<br/>tests, build, bundle check]
        s[secrets: gitleaks]
    end
    ci -->|green| rd[Render redeploys backend<br/>migration, then serve]
    ci --> vc[Vercel redeploys frontend]
```

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind CSS |
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy, psycopg 3 |
| Database | Postgres on [Neon](https://neon.com), with Alembic migrations |
| Hosting | [Vercel](https://vercel.com) (frontend), [Render](https://render.com) (backend, Docker), Neon (database), all free tiers |
| Quality | `ruff`, `mypy` (strict), `pytest`, Vitest + Testing Library |
| CI | GitHub Actions, `gitleaks` secret scanning |
| Tooling | `uv`, `pnpm`, Docker, the GitHub and Neon CLIs |

Planned for later milestones: LLM providers (Gemini, Groq, OpenRouter) behind our own router, pgvector for the RAG test corpus, the MCP Python SDK, Playwright end-to-end tests. See the [milestone plan](docs/Redflag_Milestones.md).

## Run it locally

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/), [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/).

```bash
# 1. Database (Postgres 16 in Docker)
docker compose up -d --wait db

# 2. Backend, at http://localhost:8000/health
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn redflag_backend.main:app --reload

# 3. Frontend, at http://localhost:3000 (second terminal)
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

On Windows PowerShell, use `Copy-Item` instead of `cp`.

## Tests and checks

```bash
# Backend (needs the database from step 1)
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest

# Frontend
cd frontend
pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm check:bundle
```

CI runs all of this on every push, plus a `gitleaks` scan. `pnpm check:bundle` fails if a database connection string reaches the browser bundle.

| Suite | What it covers | Tests |
|---|---|---|
| Backend over HTTP, real Postgres | healthy and degraded replies, no secret leaks, CORS, startup checks, URL handling | 8 |
| Frontend page, network faked | healthy, degraded, waking-up with retry, gives-up states | 4 |

## Configuration and secrets

| Variable | Set in | Secret? | Notes |
|---|---|---|---|
| `DATABASE_URL` | Backend host (Render) | **Yes** | Neon pooled URL. Never commit it |
| `DATABASE_URL_UNPOOLED` | Backend host (Render) | **Yes** | Neon direct URL. Migrations prefer it when set |
| `FRONTEND_ORIGIN` | Backend host (Render) | No | Exact frontend address: `https`, no trailing slash. This is the CORS allow-list |
| `NEXT_PUBLIC_API_URL` | Frontend host (Vercel) | No | The backend address. Public by design |

`.env` files are git-ignored, and `.env.example` files list names only. When you paste a URL into a host's settings, paste only the URL, with no quotes. The backend forgives stray quotes and spaces, but it is cleaner without them.

`NEXT_PUBLIC_` values are baked in when the frontend is built, so changing one needs a redeploy.

## Deploying

Everything runs on free tiers. Setup order matters, because each side needs the other's address:

1. **Neon**: create a project. Keep the pooled and direct connection URLs.
2. **Render**: new Web Service from this repo. Language Docker, root directory `backend`, instance type Free, health check path `/health`, auto-deploy after CI passes. Set the three backend variables above.
3. **Vercel**: import this repo. Root directory `frontend`. Set `NEXT_PUBLIC_API_URL` to the Render address, then deploy.
4. **Render again**: set `FRONTEND_ORIGIN` to the Vercel address so the browser may call the backend.

The full walkthrough, with the reasoning behind each choice, is in [docs/M0-setup.md](docs/M0-setup.md).

## Troubleshooting

Most problems on the live site come from free-tier behavior, not bugs. Find your symptom:

| What you see | Likely cause | What to do |
|---|---|---|
| **"Waking up the backend…"** for up to about a minute | Render sleeps after 15 minutes idle and takes about a minute to start | Wait. This is normal after any quiet period |
| **"Could not reach the backend"** after 90 seconds | The Render service is down, suspended or failed to deploy. Render gives 750 free hours a month, and when they run out the service is suspended until the next month | Open the Render dashboard, check the service status and **Logs**, and redeploy if needed |
| The page loads but never gets past "waking up", and the browser **Console** shows a red CORS error. The Network tab may still show **200** | `FRONTEND_ORIGIN` does not exactly match the page's address: wrong address, `http` instead of `https`, a trailing slash, or quotes | Set `FRONTEND_ORIGIN` to the exact address in the browser bar (the production address, not a per-deployment one) and redeploy the backend |
| **"Backend is running, but its database is not responding"** | Neon is unreachable: wrong `DATABASE_URL`, or the free quota is used up (100 compute-hours or 0.5 GB of storage), or the database is still waking | Reload after a few seconds. Then check the Neon dashboard for quota and status, and the `DATABASE_URL` in Render |
| The frontend still calls the old backend address after you changed `NEXT_PUBLIC_API_URL` | The value is baked in at build time | Redeploy the frontend on Vercel |
| Render deploy fails with `Could not parse SQLAlchemy URL` | The URL value is malformed, often with a stray quote or label copied along | Paste the bare URL, starting with `postgresql://` |
| Render deploy never starts after a push | Auto-deploy waits for CI to pass, and CI failed | Fix the failing CI job, then push again |
| Vercel deployment is paused or builds fail to start | Hobby plan usage limits reached, or it is being used commercially | Check Vercel's usage page. Hobby is for non-commercial use |
| Locally, `/health` returns 503 or the backend cannot connect | The local database is not running | Start Docker Desktop, then `docker compose up -d --wait db` |
| `pnpm typecheck` fails with `Cannot find name 'LayoutProps'` | Next.js route types have not been generated | `pnpm typecheck` already runs `next typegen`. If you ran `tsc` directly, run `pnpm exec next typegen` first |
| CI fails on the `secrets` job | `gitleaks` found something that looks like a credential | Remove it, and rotate the credential if it was real |

## Limitations

- **Cold starts.** The free backend host sleeps after 15 minutes without traffic and takes about a minute to wake. Neon sleeps after 5 minutes and wakes in a few seconds. The first visit after a quiet spell is slow by design.
- **Free-tier ceilings.** Render: 750 free instance hours a month. Neon: 0.5 GB of storage and 100 compute-hours a month. Vercel Hobby: non-commercial use, with usage quotas. When a ceiling is hit, that part of the app stops until the quota resets. Limits were last checked on 2026-10-18 and change often.
- **No security testing yet.** Milestone 0 contains no attack library. A "healthy" result means the backend and database respond. It is **not** a security claim.
- **Not complete security.** Even when testing arrives, an OWASP checklist is not proof an app is secure. Reports will always separate tested, untested and inconclusive risks.
- **No accounts, rate limiting or end-to-end browser tests yet.**
- **Model providers are free tiers too.** Once added, Gemini, Groq and OpenRouter have small, changing quotas, so scans will be budgeted and cached. When a quota runs out, scans will be marked skipped or errored, never silently passed.
- **Database versions differ slightly.** Neon runs Postgres 18. Local development and CI use Postgres 16.

## Roadmap

Built one milestone at a time. Each ends with a live deployment that is checked before the next begins.

| # | Milestone | Status |
|---|---|---|
| M0 | Foundation and first deploy | ✅ Done |
| M1 | Model router: provider fallback, caching, budgets | Next |
| M2 | Demo targets and sandbox: vulnerable and hardened bots | Planned |
| M3 | Scan engine with deterministic verdicts | Planned |
| M4 | Dashboard and reports | Planned |
| M5 | LLM judge with measured accuracy | Planned |
| M6 | Policy builder | Planned |
| M7 | Adaptive and multi-turn attacks | Planned |
| M8 | External targets (HTTP and MCP) | Planned |
| M9 | Regression testing and CI gate | Planned |
| M10 | Launch polish | Planned |

Details: [docs/Redflag_Milestones.md](docs/Redflag_Milestones.md).

## Project layout

```
Redflag/
├── backend/            FastAPI app, migrations, tests, Dockerfile
├── frontend/           Next.js app and its tests
├── docs/               requirements, milestones, setup notes, designs, specs, plans
├── .github/workflows/  CI
├── docker-compose.yml  local Postgres
├── neon.ts             Neon project configuration
└── README.md
```

## Documentation

- [M0 setup and what it achieved](docs/M0-setup.md)
- [Milestone plan](docs/Redflag_Milestones.md)
- [Requirements specification](docs/Redflag_Requirements_Specification.docx)
- [M0 design](docs/superpowers/specs/2026-10-18-m0-foundation-design.md) and [build plan](docs/superpowers/plans/2026-10-18-m0-foundation-plan.md)
