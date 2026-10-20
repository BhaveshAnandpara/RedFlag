# Wave 2: attack variations, multi-turn, CI, quick scan, judge accuracy and MCP checks

Built 2026-10-20 as one batch (phases W1 to W8; W9 was polish and this documentation). Plan: [wave 2 combined plan](superpowers/plans/2026-10-20-wave2-combined-plan.md). Why these were chosen: [Observations and competitors](Observations_and_Competitors.md).

Every rule from earlier milestones still holds: Redflag never says a bot is "secure" or "safe", reports keep tested, untested and unclear apart, the endpoint key is never stored, logged or shown to any AI, only one scan runs at a time, and the AI judge is described as unchecked unless you have labeled results to measure it.

## What is new, by phase

| Phase | What you get | Where |
|---|---|---|
| W1 Attack variations | The same attack rewritten in eight fixed ways, added to a setup version | Select-tests page of `/setup`, "Add attack variations" |
| W2 Multi-turn | An attacker AI that continues a conversation, up to 4 turns | Strategies marked multi-turn |
| W3 Run again | Re-run a finished scan of your bot and see what changed | "Run these tests again" under a finished scan |
| W4 CI | API tokens, a command, a GitHub Action | Token panel on a finished scan, `ci/redflag-ci.mjs`, `.github/actions/redflag-scan` |
| W5 Framework tags, report | MITRE ATLAS tags next to each OWASP risk, a print-friendly report | Overview tab, "Print report" |
| W6 Quick scan | Connect a bot, say hello, run a built-in starter pack | `/quick` |
| W7 Judge accuracy | Mark whether the judge was right; see agreement per risk | Conversations tab |
| W8 MCP checks | Check an MCP server's tool descriptions, and optionally call its tools with manipulated text | `/mcp` |

## W1 and W2: variations and multi-turn

Eight strategies rewrite an attack prompt without a model, so they cost nothing and give the same result every time: **authority**, **role-play**, **hypothetical**, **urgency**, **override**, **base64**, **document** (the request hidden in a note to summarise) and **system spoof**. `GET /strategies` lists them. `POST /setups/{id}/versions/{n}/tests/variations` adds variations of the ticked attack tests (normal requests are never varied), each marked with its strategy and ticked. The cap per setup version is `SETUP_MAX_TESTS`; past it the call fails with `test_cap_reached`.

A multi-turn test is a short conversation. Redflag's own model (the **attacker**, with its own budget) reads the goal, the rules and the conversation so far and writes the next message, up to `MULTI_TURN_MAX_TURNS` turns (default 4). The run stops when the judge says the bot broke a rule. The judge reads the whole conversation and the result stores every turn. Only the OpenAI-compatible format can carry a conversation; a custom template is single-turn and says so. If the attacker or judge cannot answer, the test is unclear, never a pass. Every turn counts against `RUN_MAX_ENDPOINT_REQUESTS` (default 150).

## W3 and W4: run again and CI

**Run again** (`POST /scans/{id}/rerun`) repeats a finished scan of your bot: same setup version, same ticked tests. The new scan is compared with the previous scan of the same setup, and the dashboard shows what was fixed, what is new and what is unchanged.

**CI.** On a finished scan, the token panel makes an API token for that setup. It is shown once and only its SHA-256 hash is stored. A token can only start a run of its own setup and read that run's result.

- `POST /ci/runs` (header `Authorization: Bearer <token>`, body `key`, `fail_on`, optional `version`, `test_ids`) starts a run; `GET /ci/runs/{id}` returns the result with a **gate**: pass, or fail with the reasons, by a severity level you choose (`critical`, `high`, `medium`, `any`), optionally failing when tests are unclear.
- `node ci/redflag-ci.mjs --fail-on high` does both calls and sets the exit code (0 gate passed, 1 gate failed, 2 something went wrong). It reads `REDFLAG_URL`, `REDFLAG_TOKEN` and `REDFLAG_TARGET_KEY` from the environment and never prints the token or the key.
- The GitHub Action is `.github/actions/redflag-scan`. A ready example with a daily schedule is [docs/examples/redflag-ci.yml](examples/redflag-ci.yml). The schedule lives in the workflow because the free host sleeps.

A passing gate means no test failed at or above your level in the tests that ran. It is not a statement that the bot is secure.

## W5: framework tags and report

Each OWASP LLM risk carries MITRE ATLAS technique tags from a fixed table with its source and date (`GET /catalog`). They appear in the dashboard and the report. "Print report" opens a print-friendly page, so "Save as PDF" in the browser gives a PDF. "Download report" gives Markdown. When judge accuracy has been measured, the report includes it.

## W6: quick scan (`/quick`)

For someone who is not a developer. Steps:

1. **How is your bot built?** OpenAI-compatible, Flowise, "Paste anything", or Other. The website-widget option is shown as coming soon (it needs a browser, which the free host cannot run).
2. **Say hello.** Redflag sends "Hello" and shows the answer: "Is this your bot's answer?" The next step only opens after you say yes. Changing any detail asks again.
3. **What kind of bot, what for, what it must never do.** Chatbot or agent; one sentence of purpose; ticked default rules you can untick, plus your own. An agent needs the "test or sandbox environment" box ticked.
4. **Run starter pack.** `POST /quick-scans` sends it all in one request and starts the run. The starter pack is a fixed library (no model call to write it): attacks for the chosen bot type, one test per rule you added, five normal requests, then variations. Progress, then the same dashboard as everywhere else, with "Tailor these tests", which opens the chat setup.

"Paste anything" reads a link, a key, a code sample, JSON or a curl command (including a Windows-copied one) in the browser, fills what it can, clears the box, and names what it found ("We found: address, key") and what is still needed, never showing the key.

Backend: `GET /quick-scans/rules`, `POST /quick-scans/check` (the hello check, limited by `QUICK_CHECKS_PER_WINDOW` per `QUICK_CHECK_WINDOW_SECONDS`), `POST /quick-scans`.

## W7: judge accuracy

In the Conversations tab (owner pages), each result with a judge verdict has **Judge was right** and **Judge was wrong**. A label is the verdict you say was correct (`PUT /scans/{id}/results/{test}/label`, `DELETE` to clear). The accuracy panel (`GET /judge-accuracy`) shows, over all labeled results:

- agreement: how many of the labeled results the judge agreed with you on;
- **false alarms**: the judge said fail, you say the reply was fine;
- **misses**: the judge said pass, you say it broke the rule;
- the same per risk, and the number each figure rests on. Below `JUDGE_ACCURACY_MIN_SAMPLE` labeled results (default 20) the numbers are called a small sample, a hint and not a measure.

Results where the judge gave no verdict are left out of the numbers and counted separately. The saved public samples have no labeling.

## W8: MCP server checks (`/mcp`)

Owner-only. Enter the server address (streamable HTTP) and a key if it needs one; the key goes in a header you can choose (`Authorization: Bearer` by default), and is never stored.

1. **Look at the tools** (`POST /mcp-scans/check`): Redflag does the handshake and lists the tools. A tool is shown as "only reads" only if the server says so itself; every other tool starts as "changes things".
2. **Static checks, always.** For every tool, plain rules (no model) look at the description and schema for: hidden instructions to the model, invisible and direction-changing characters, wording about credential files or sending data out, and open-ended parameters that reach files, commands or queries. A clean result is not proof of safety.
3. **Manipulated calls, only for tools you tick.** For a ticked tool's text parameters Redflag sends a path-traversal string, injection strings, a very large value and an instruction hidden in the text; other required parameters get harmless values. The AI judge reads what the tool sent back. A tool you mark "changes things" is only called if you also confirm the server is a test or sandbox. At most `MCP_CALLS_PER_TOOL` calls per tool and `MCP_MAX_CALLS` per run.

Same safety rules as for chat endpoints: public addresses only (private, internal and Redflag's own are refused, and the call goes to the address that was checked), no redirects, a reply size cap, and a failed call is an error with its cause, never a pass. Results use the same dashboard, with risks LLM01, LLM02, LLM05, LLM06 and LLM10.

## New settings

All optional, with the defaults in `backend/src/redflag_backend/settings.py`:

| Setting | Default | Meaning |
|---|---|---|
| `RUN_MAX_ENDPOINT_REQUESTS` | 150 | Most requests one run may send to your endpoint (each turn counts) |
| `MULTI_TURN_MAX_TURNS` | 4 | Turns in a multi-turn attack |
| `ATTACKER_BUDGET_MAX_REQUESTS`, `_TOKENS`, `_SECONDS` | see settings | The attacker's own budget per run |
| `SETUP_MAX_TESTS` | 200 | Tests in one setup version, including variations |
| `QUICK_CHECKS_PER_WINDOW`, `QUICK_CHECK_WINDOW_SECONDS` | 20, 600 | Limit on hello checks |
| `JUDGE_ACCURACY_MIN_SAMPLE` | 20 | Labeled results needed before accuracy is not called a small sample |
| `MCP_MAX_CALLS`, `MCP_CALLS_PER_TOOL` | 60, 8 | Limits on tool calls in an MCP check |

**`/quick` and `/mcp` have no owner password.** Their calls (rule list, hello check, MCP tool listing, starting a scan, and reading a scan back with the secret view key that start returned) are open to anyone; everything else stays owner-only. Proof that the person owns the server they test is not built, so anyone with the link can make Redflag send attack traffic to any public address (private and internal addresses are still refused) and use the judge's model quota. The existing limits still apply (one scan at a time, request and token budgets, a cap on hello checks), but there is no per-visitor limit. The finished page on these two pages is the dashboard only; Run again, CI tokens and Label mode need the owner password.

One new migration: `judge_labels` (and `ci_tokens` earlier in the wave). Run `alembic upgrade head` (the host does this on deploy).

## How to check it

Backend tests need the database (`docker compose up -d db`):

```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
cd ../frontend
pnpm lint && pnpm typecheck && pnpm test && pnpm build && pnpm check:bundle
```

By hand: open `/quick`, paste a curl command for a bot, say hello, run the starter pack, open the Conversations tab and label a result, then open the report. Open `/mcp`, look at a server's tools, run with nothing ticked (description checks only), then tick one read-only tool.

## Not built, on purpose

Accounts, roles and proof that you own the server you test (still required before any public use); chat-widget and browser-agent testing; runtime guardrails; a hosted scheduler.
