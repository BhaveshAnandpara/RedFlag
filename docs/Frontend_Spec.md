# Redflag frontend specification (as built, after M5)

> **Update (2026-10-20):** the home page is now the animated design page from `design/explore/home.html`, served at `/` together with `/scan.html` (a demo scan shown as a chat) and `/results.html` (the report), all copied into `public/design` at build and linked to each other. Part 4.1 below describes the old Next.js home page, which was removed; the health card component still exists but is no longer shown. The Next.js pages `/how-it-works`, `/results`, `/scan` (owner) and `/router` (owner) still exist and are no longer linked from the home page.

This document describes the frontend **as it was after M5**: every page, what it shows, what it can do, how it gets its data, and the rules it keeps. It is the starting point for the UI work. It describes what exists, not what is planned. Part 9 lists the gaps I noticed in the current UI, as observations, not decisions.

Related: [README](../README.md) · [Milestone plan](Redflag_Milestones.md) · [M4 setup (dashboard)](M4-setup.md) · [M5 setup (AI judge)](M5-setup.md)

## 1. What the frontend is

- **Product:** Redflag is a final security check for AI apps. The frontend is how a person sees what Redflag tests and what a scan found.
- **Stack:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, `pnpm`. Fonts: Geist and Geist Mono are loaded, but `body` is set to Arial (see Part 9). Hosted on Vercel Hobby at `https://red-flag-gules.vercel.app`.
- **Backend:** a FastAPI service at `NEXT_PUBLIC_API_URL`. The frontend never holds an AI key. It calls the backend only for the health check and, on the two owner-only pages, for the router and scan APIs.
- **Two kinds of visitors:**
  - **A first-time visitor** (no password): reads the home page, **How Redflag tests your AI**, and **Saved scan results**. These pages are public and read-only, and the last two make no network request.
  - **The owner** (has the password): also uses `/scan` to run live scans and `/router` to test the model router. Neither is linked from anywhere and both are kept out of search engines.

## 2. Site map

| Route | Who | Purpose | Data comes from | Network calls |
|---|---|---|---|---|
| `/` | Everyone | Name, one-line pitch, two links, backend health card | Backend `GET /health` | Yes, health only |
| `/how-it-works` | Everyone | Recorded attacks on a weak and a hardened demo bot, side by side | `src/data/recordings.json`, built into the site | None |
| `/results` | Everyone | Two saved real scans (weak and hardened) in the full dashboard, read-only | `src/data/sample-scans.json`, built into the site | None |
| `/scan` | Owner only | Unlock, pick a bot, run a live scan, watch progress, read results | Scan API (`/bots`, `/scans`, `/scans/{id}`) | Yes, with the password |
| `/router` | Owner only | Test the model router: chat, provider status, pretend failures, budget | Router API (`/llm/...`) | Yes, with the password |

Navigation today: the home page links to `/how-it-works` and `/results`. `/how-it-works` links to `/results`. There is no header, footer or menu, and no page links back to the home page. `/scan` and `/router` are reached only by typing the address.

## 3. Global behaviour

### 3.1 Layout
Each route renders its own `<main>` inside the root layout (`<html lang="en">`, `<body>` as a full-height flex column). Widths: home 2xl, `/router` 2xl, `/scan` 3xl, `/how-it-works` and `/results` 5xl (wide, for side-by-side content). Padding is 24px sides, 48px top and bottom. Metadata: title "Redflag" and a one-line description; `/scan` and `/router` set `robots: noindex`.

### 3.2 Colour and words (the tone system)
Defined once in `globals.css` as CSS variables, with light and dark values (dark follows the system setting, there is no toggle):

| Tone | Used for | Meaning |
|---|---|---|
| green | PASS | The test found no problem |
| red | FAIL | The test found a problem |
| yellow | INCONCLUSIVE, ERROR, UNAVAILABLE (judge) | Unclear: could not decide or complete |
| grey | NOT APPLICABLE, NOT TESTED, NOT RUN (judge) | Nothing was checked |

Each tone has a strong colour, a soft background and a readable ink colour. **Colour is never the only signal:** every status badge carries its word. Tailwind utility names: `border-tone-*`, `bg-tone-*-soft`, `text-tone-*-ink`.

### 3.3 Wording rules (enforced by tests)
- A conclusion never says a bot is "safe", "secure" or "ready". It states counts first.
- It always ends: "This is not a guarantee of security. It only reports what these tests checked."
- An untested or unclear risk is never green. A banner is green only if nothing failed, nothing was unclear and every risk had a result.
- The AI judge is always described as **not checked for accuracy**.
- Saved scans are always labelled "Recorded on [date] with [models]", so they never pass as live.

### 3.4 Accessibility
- Every chart has a text equivalent (a list beside the donut, text inside each risk bar).
- The tab strip is a real `tablist` with arrow, Home and End keys.
- Status badges, tables, forms and conversations have labels (`aria-label`, `role="group"`, `role="note"`, `role="status"`, `role="alert"`).
- Works in light and dark mode. Layout is a flowing column; the tests table scrolls sideways on narrow screens.

### 3.5 Security rules the frontend keeps
- **The owner password is held in memory only.** It is never stored in the browser (no localStorage, cookie or URL) and is sent only as the `X-Owner-Token` header.
- No key, token or connection string may reach the browser bundle: `pnpm check:bundle` scans the build, and the saved samples are checked against key-shaped text.
- `NEXT_PUBLIC_API_URL` is the only environment value the frontend uses, and it is public by design.
- Visitors can never start a scan or reach an owner-only endpoint from a public page.

## 4. Pages

### 4.1 Home (`/`)
- **Elements:** heading "Redflag"; line "A final security check for AI apps before you release them."; two text links ("See how Redflag tests an AI", "See saved scan results"); the **backend health card**.
- **Health card (`HealthStatus`):** asks `GET /health`. States, each with a visible label:
  - *Waiting*: "Waking up the backend…" with a seconds counter (the free host sleeps; the first visit can take about a minute). Retries every 3 seconds, up to 90 seconds.
  - *Healthy*: database ok, version, commit.
  - *Degraded*: backend up, database not responding.
  - *Error*: gave up after 90 seconds, "Try reloading".

### 4.2 How Redflag tests your AI (`/how-it-works`)
- **Purpose:** explain, without a live call, what Redflag does: it sends an AI the kind of messages an attacker would, then checks the reply and everything the AI did.
- **Header:** title, a short explanation, three bullets (weak bot has no protection, hardened bot has defenses, every tool is pretend and all data is made up), and a note that these are **recordings of real runs, never edited, not live**.
- **Four attack cards**, one per recorded attack. Each card has: the attack title, "What we are checking", the attack message, and two **run panels** side by side (stacked on small screens): *Weak bot* and *Hardened bot*.
- **A run panel shows:** which defenses were on, the bot's **reply**, the **tool-call log** (tool, arguments, outcome), a **verdict box** (PASS, FAIL or INCONCLUSIVE, the evidence, "How we decided" with the rule), and "Recorded on [date] with [model]".
- **Footer link:** "See a full scan of both bots, with charts and a comparison" (to `/results`).
- **Note:** verdicts here come from the plain rules only (recorded at M2, before the judge).

### 4.3 Saved scan results (`/results`)
- **Purpose:** show a complete scan result to someone who has never used Redflag, safely.
- **Empty state:** "No saved scans yet."
- **Otherwise:** heading, an explanation that these are saved real scans (nothing runs a scan or calls an AI), a **"Recorded on [date] with [models]"** box, then the full **Dashboard** (Part 5) in read-only mode.
- **Behaviour:** opens on the weak scan. The History tab switches between the two saved scans. The Compare tab opens ready as weak versus hardened.
- **Currently saved:** scan #4 (weak) and scan #5 (hardened), recorded before the judge, so the judge shows as NOT RUN.
- **Not possible here:** running a scan, entering a password, any network request.

### 4.4 Scan (`/scan`, owner only)
- **Locked state:** heading "Scan", "Locked: enter the owner password", a password field, an **Unlock** button. A wrong password shows "That password was not accepted." An unreachable backend shows "Could not reach the backend. It may still be waking up."
- **Unlocked state:**
  - A **Bot** dropdown (the demo bots from `GET /bots`) and a **Run scan** button (disabled while a scan runs).
  - Plain error messages for: a scan already running, no model configured for the bots, unknown bot, backend unreachable.
  - **Progress view** while a scan runs: "Scan #N", the bot, "Status: running", "X of 16 tests done", and a live list of finished tests with their status badges. It checks every 2 seconds. After 30 seconds with no new result it adds "No new result yet. It may be waiting for a free-tier limit to clear."
  - **When it finishes:** the Dashboard opens on the result (Part 5). Interrupted scans show their note.
  - **Earlier scans** list (before any scan is open): "Scan #N · bot · status · N failed" with an **Open** button each.
- **Limits:** one scan at a time; only the demo bots can be scanned; there is no scan configuration, the single button runs all 16 tests.

### 4.5 Model router test page (`/router`, owner only)
A test tool for the model router built in M1. It is plain and functional, and is not meant for visitors.
- **Locked state:** password field and Unlock (same pattern as `/scan`).
- **Chat:** a message box, **Send**, and a "keep the conversation" option. Replies show which provider and model answered, whether the answer was saved (cached), and whether a paid model was used. A **Start a new session** button clears the conversation and starts a new budget.
- **Providers and test tools:** a list of providers (Groq, Gemini, OpenRouter) with status words: no key, ready, or cooling down with seconds left. Per provider, a button to **pretend it is out of quota** for 60 seconds, to watch fallback. A **Clear memory** button empties the saved answers (`/llm/test/clear-cache`).
- **Budget for this session:** requests, text (tokens) and seconds used against their limits.
- **Last request:** the attempt log (each provider tried, outcome and time), and a "Switched from X to Y" notice when fallback happened.
- **Errors in plain words:** wrong password, budget reached, every provider failed, no provider configured, a provider's key rejected, invalid request.

## 5. The dashboard (shared by `/scan` and `/results`)

One component, `Dashboard`, takes one scan and shows it. It is the heart of the product UI.

### 5.1 Header
"Scan #N", the bot name, status, start time (UTC), an optional note, and a **Download report** button (a Markdown file built in the browser, named `redflag-scan-N.md`).

### 5.2 Tabs
**Overview · Tests · Conversations · Compare · History** (keyboard: arrows, Home, End).

**Overview**
- **Conclusion banner** (tone follows the overall result: red if anything failed, yellow if anything was unclear or any risk had no pass or fail result, green only otherwise). It holds: a headline in counts ("4 of 11 attack tests failed, 2 of them critical."), then bullet lines: attack success rate with a 95% range and a small-sample note under 20 tests; tests that could not be completed; normal requests that worked; risks with no result; the **AI judge lines** (what the judge failed that the rules passed, unavailable verdicts, "has not been checked for accuracy", or "No AI judge ran on this scan"); and the closing "not a guarantee" line.
- **AI judge note** (`role="note"`): a permanent short statement that the judge is unchecked and that either side failing a test fails it, or that no judge ran.
- **Results donut** with a text list (Pass, Fail, Unclear, Not applicable, with counts and percentages).
- **Critical failures:** red cards with title and evidence, or "No test rated critical failed."
- **What this scan checked and did not check:** ten **risk bars** (the OWASP LLM Top 10), each stacked by status, with a state word (Tested, Attempted no result, Not tested) and counts. Untested risks are grey.
- **Settings this scan ran with:** bot and config version, defenses, models that answered, suite version, risk list, budgets, and the planted secret.

**Tests**
- A table: **Result** (badge), **AI judge** (badge), **Test**, **Risk**, **Severity**, **Model**.
- Filters: by result, by risk (including "Normal requests"), by severity (including "not rated"). A **Sort by severity** toggle puts critical first. "No tests match those filters." when empty.

**Conversations**
- One card per test (badge, title, risk, severity) with a **Show evidence** button that opens: the message sent, the bot's reply, the **tool-call log** with arguments and outcome, the combined evidence, **two labelled blocks, "Plain rules" and "AI judge"** (status, output or reason, and the judge's model), a line when the two **disagree**, the rule, "How to fix", and which model answered. A result with no judge shows "The AI judge did not run on this test."

**Compare**
- A dropdown to pick another scan. Shows: a one-line statement of whether the **same model(s)** answered both (green if identical, yellow with a warning if not); a note when only one scan had the judge; a note when the two ran different versions of the test library; attack failures in each; **tests that changed result**; tests in only one scan.

**History**
- A list of scans ("Scan #N · bot · status · N failed", "shown now" on the open one), each with an **Open** button.

### 5.3 Report (Markdown)
Sections: conclusion, settings, **The AI judge**, what was tested (table including the judge column), failures (severity, evidence, both outputs, rule, how to fix), could not be decided or completed, did not apply, normal requests, risks not tested, and the closing line.

### 5.4 Read-only mode
On `/results` the same component is fed the saved file. There is no run button and no password, and Compare and History read from the file, not the network.

## 6. Shared pieces

| Piece | File | What it does |
|---|---|---|
| `Dashboard` | `components/dashboard.tsx` | Tabs, Overview, Tests, Conversations, Compare, History, report download |
| `Donut`, `RiskBars` | `components/dashboard-charts.tsx` | Hand-made SVG charts with text equivalents (no chart library) |
| `StatusBadge`, `JudgeBadge`, `TONE_CLASS` | `components/status.tsx` | Coloured badges that always show their word |
| `ScanPage` | `components/scan-page.tsx` | Owner scan flow: unlock, run, poll, open |
| `ResultsPage` | `components/results-page.tsx` | Public saved-scan wrapper around the dashboard |
| `HowItWorks` | `components/how-it-works.tsx` | The recorded-attack explainer |
| `HealthStatus` | `components/health-status.tsx` | The health card on the home page |
| `RouterTestPage` | `components/router-test-page.tsx` | The owner's router test tool |
| analytics | `lib/analytics.ts` | Counts, donut slices, risk bars, critical failures, attack success rate and Wilson range, the conclusion, comparison, banner tone, judge state and summary |
| report | `lib/report.ts` | The Markdown report |
| scan types | `lib/scan.ts` | The shape of the scan API's responses |
| samples | `lib/samples.ts` | Saved-scan helpers and the "Recorded on" label |
| recordings | `lib/recordings.ts` | The shape of the recorded attacks |

## 7. Data the frontend reads

- **Scan API** (owner password header): `GET /bots`, `POST /scans`, `GET /scans`, `GET /scans/{id}`. A scan has settings, models used, a per-risk summary, and per-test results: message, reply, tool calls, evidence, rule, severity, fix note, model, and the plain-rules and AI-judge outputs.
- **Router API** (owner password header): `/llm/providers`, `/llm/chat`, `/llm/test/fail`, `/llm/test/clear-cache`.
- **Health:** `GET /health`.
- **Built-in files:** `data/recordings.json` (four attacks, weak and hardened, recorded at M2) and `data/sample-scans.json` (scans #4 and #5). Updated with `pnpm export:samples --weak <n> --hardened <n>`, which refuses unfinished scans and key-shaped text.

## 8. How it is tested

Vitest, Testing Library and user-event; the network is faked and nothing calls a live model. 146 tests across: health card (4), router test page (21), explainer page (11), scan page (9), dashboard (36), analytics, comparison and report functions (45), saved sample rules (14), public results page (6). `pnpm lint`, `pnpm typecheck`, `pnpm build` and `pnpm check:bundle` also run in CI.

## 9. Gaps in the current UI (my observations, for you to decide)

These are what I noticed reading the code. None is decided or planned.

1. **No shared navigation.** There is no header, logo link, footer or menu. Pages are islands, and nothing links back to the home page.
2. **Visually plain.** The look is default Tailwind with bordered boxes and almost no spacing system, brand colour, icons or illustration. The home page is a title, a line and two text links.
3. **Font mismatch.** Geist is loaded but `body` is set to Arial, so Geist is not used.
4. **The home page doesn't explain the product.** There is no "what it does", no example result and no clear first action. The best explanation sits two clicks away.
5. **The dashboard is long and dense.** The Overview stacks seven sections, the conclusion is a bullet list, and the judge lines make it longer.
6. **Tables and cards are not tuned for phones.** The Tests table scrolls sideways, and the Conversations cards are long.
7. **Charts are basic.** A donut and stacked bars, with no scan-over-scan trend and no severity chart.
8. **`/scan` and `/router` are unlinked** and look like internal tools. The owner has no menu to reach them.
9. **Loading and empty states are minimal** (text only, no skeletons).
10. **Default Next.js sample assets** (`file.svg`, `globe.svg` and others) are still in `public/` and unused.
11. **Dark mode follows the system only**, with no toggle.
12. **`/how-it-works` shows plain-rule verdicts only** and does not mention the AI judge.
13. **No page for the judge's reasoning** beyond the Conversations tab, and no page for policies (that arrives with M6).
