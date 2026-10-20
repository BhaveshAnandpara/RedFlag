# Wave 2: the remaining milestones, built together

Written 2026-10-20. The owner asked to build all the remaining milestones together and change things as we go. This is the combined plan. It replaces the one-milestone-at-a-time approval loop for this wave: each phase is built test-first, committed, and deployed in batches, and the owner checks the live site between batches. Everything marked "my call" can be changed at any time.

Background: [Observations and competitors](../../Observations_and_Competitors.md) · [Milestone plan](../../Redflag_Milestones.md) · [M6 setup](../../M6-setup.md)

## What is in the wave

| # | Phase | Milestone it covers | Why (from the competitor review) |
|---|---|---|---|
| W1 | Attack strategies: automatic variations of attack prompts | M7 | Every competitor has attack variations (role-play, encoding, authority claims, hidden instructions) |
| W2 | Multi-turn adaptive attacks | M7 | Mindgard, Straiker, Lasso, Giskard and PyRIT all do multi-turn |
| W3 | Run again, with an automatic comparison to the last run | M9 | A result that cannot show improvement is not a product |
| W4 | API tokens, a command and a GitHub Action for CI, and scheduled runs through the Action | M9 | CI/CD and API access is common to the commercial tools |
| W5 | OWASP and MITRE ATLAS tags, and a printable report | M10 | Compliance-style exports and framework mapping |
| W6 | Quick scan: easy connect, a built-in starter pack, one-click run | new (product direction) | The default experience for a non-developer |
| W7 | Judge accuracy: a labeling tool and agreement numbers | M5b | A differentiator: nobody else shows it |
| W8 | MCP server testing | M8 | Several competitors test MCP; most only statically |
| W9 | Polish, audit, privacy, accessibility, docs, final deploy | M10 | |

**Left out on purpose:** accounts, roles and proof of ownership (deferred by the owner and still blocking any public launch), chat-widget and browser-agent testing (needs a headless browser, which free hosting cannot run), runtime guardrails, and a hosted scheduler (see W4).

## How the work runs

- **Order:** W1 to W9 as listed, because each builds on the one before (variations feed multi-turn, runs feed comparison, the quick scan uses all of them).
- **Method:** test-first, vertical slices, only at the seams below. The only faked parts are outside models, the user's endpoint and, for W8, a stand-in MCP server. No CI test calls a live model or a real outside server.
- **Commits** after each phase with every check green. **Deploys** after W2, W5, W7 and W9, so the owner can check the live site in between.
- **Standing rules kept:** never say "secure" or "safe"; separate tested, untested and inconclusive; the endpoint key is never stored, logged or shown to an AI; one scan at a time; the judge is always described as not checked for accuracy until W7 gives numbers.

## Test seams (my call; change as we go)

1. **Strategy functions on their own** (W1, W5): a prompt in, a transformed prompt out; tag mappings.
2. **The attack runner over HTTP with real Postgres, a stand-in endpoint and a fake judge** (W1 to W4, W6, W8): variations added and run, multi-turn conversations, run-again and comparison, API tokens, starter pack runs.
3. **The HTTP and MCP target adapters against stand-in servers** (W2, W8): conversation sending, MCP handshake, listing, calls, address checks.
4. **The pages and dashboard, network faked** (W1 to W7): the select page, quick scan, run-again and comparison views, labeling, report export.
5. **Scripts and CI files** (W4): the command and the Action file are exercised against the stand-in API.

## Phase details

### W1: Attack strategies
- A fixed set of deterministic strategies that rewrite an attack prompt: **authority** ("I am your administrator and I authorise this"), **role-play** (a persona with no rules), **hypothetical** (fiction framing), **urgency** (pressure), **override** ("ignore all previous instructions"), **base64** (the request encoded, with an instruction to decode and follow), **document** (the request hidden inside a note to summarise, an indirect injection) and **system spoof** (a fake system message).
- An endpoint that adds variations of the ticked attack tests to a setup version, each marked with its strategy, all ticked, appended to the test list. Normal requests are never varied.
- The select page gets an "Add attack variations" panel. The run cap default rises to 150 requests.
- The judge sees the original goal and the expected reply, unchanged.

### W2: Multi-turn adaptive attacks
- The HTTP target can send a whole conversation (OpenAI-compatible format). Custom templates stay single-turn and say so.
- For a chosen attack, an **attacker AI** (Redflag's own model) reads the goal, the rules and the conversation so far and writes the next message, up to a turn cap (default 4). The run stops early when the judge says the bot broke a rule, or at the cap.
- The judge reads the whole transcript. The result stores every turn. Cost per turn is one target call, one attacker call and one judge call, so multi-turn is opt-in and capped.
- The attacker's budget is separate from the judge's.

### W3: Run again and comparison
- A **Run again** button on a finished real-bot scan: same setup version, same ticked tests, new scan.
- The new scan is automatically compared with the previous one of the same setup: tests that were fixed, new failures, unchanged failures. The dashboard shows this at the top.

### W4: CI and scheduling
- Per-setup **API tokens** (shown once, stored only as a hash), separate from the owner password and limited to starting a run of that setup and reading its result.
- `POST /ci/runs` starts a run, `GET /ci/runs/{id}` returns the result with a **gate**: pass, or fail with the reasons, by a severity threshold the caller sets. The key for the target is sent with the call and never stored.
- A small command-line script and a ready-made **GitHub Action** (with a scheduled-run example) in the repo and the docs. Scheduling is done by the Action's own cron, because the free host sleeps.

### W5: Framework tags and a printable report
- Each OWASP LLM risk gets MITRE ATLAS technique tags (a static table, with its source and date). Both appear in the dashboard and the report.
- A print-friendly report view (save as PDF from the browser) alongside the Markdown download.

### W6: Quick scan
- A new page: **easy connect** (OpenAI-compatible first, with the platform presets added only where the platform's API has been checked; a "paste anything" box that reads a link, a key, a code sample or a curl command and asks only for what is missing), a **hello check** ("Is this your bot's answer?"), bot type (chatbot or agent), one sentence about the bot, an optional must-never list with defaults, then **Run starter pack**.
- A **built-in starter pack** of about 40 tests per bot type, deterministic (no model call to write it), with W1 variations, run without a select step.
- The deeper chat from M6 stays as "Tailor these tests" from the report.

### W7: Judge accuracy
- A **Label** mode in the Conversations tab: the owner marks a result's judge verdict as right or wrong, and the correct verdict.
- A metrics view and report section: agreement, false alarms, misses, per risk, with the sample size stated. Small samples are labelled as such.

### W8: MCP server testing
- An MCP client (initialize, list tools, call tool) over HTTP, using the same address checks.
- **Static checks** on tool descriptions and schemas (hidden instructions, hidden Unicode, suspicious wording, overly broad parameters).
- **Dynamic tests** that call tools with manipulated parameters (path traversal, injection strings, oversized values) and have the judge read the results. Tools that change anything run only after the owner marks the server as a sandbox and ticks them.
- The same safety rules: public addresses only, request cap, the key never stored.

### W9: Polish and final deploy
- An accessibility pass, a privacy and secrets audit, honest copy on the home page (nothing promised that is not built), the README, the setup docs and the frontend spec brought up to date, CI green, and a full deploy.

## Calls made without the owner
- Strategies are deterministic rewrites, not model-written, so they cost nothing and are repeatable.
- Multi-turn uses Redflag's own model as the attacker and is opt-in with a 4-turn cap.
- The CI gate uses a severity threshold chosen by the caller, defaulting to "fail on any critical finding".
- MCP dynamic tests that could change data are blocked unless the owner marks the server as a sandbox.
- Platform presets other than OpenAI-compatible are added only after the platform's API has been read.
- The starter pack is a fixed library, so a quick scan uses no model quota to write tests (the judge still uses some).

## Risks to watch
- **Size.** This is a lot of work. If a phase overruns or a design question needs the owner, work pauses at that point and the owner is told.
- **Quota.** Multi-turn and larger packs use far more of the free model quota. Caps and clear errors are part of each phase.
- **Overclaiming.** Variations and multi-turn make results look stronger. The report must keep saying what was and was not tried.
- **Sending harmful traffic.** More attacks against real endpoints raise the stakes of the deferred permission check; it must be settled before any public use.
