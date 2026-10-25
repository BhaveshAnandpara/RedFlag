# New testing architecture: "Test your AI" (design)

Status: draft for approval. Date: 2026-10-26.
Builds on: [M6 setup](../../M6-setup.md), [Wave 2 setup](../../Wave2-setup.md), [M5 judge](../../M5-setup.md), the existing `setups/`, `scan/`, `mcp/`, `targets/` and `attacks/` backend packages. Backlog items: #2 (this design) and #3 (measured cost estimate, parked).

## Intent and why

Redflag should break a user's AI the way a real attacker would: try many angles, push harder where defences hold, and show proof for every finding. Today the engine tests a bot with up to 30 generated single-message tests (plus a few multi-turn ones), and the judge decides alone for a real bot because Redflag cannot see the bot's tool calls. This design replaces that with a plan built from recon, run by several attacker personas, decided by code wherever code can decide, and kept as a replayable suite.

Two rules run through everything:

- **LLMs think, code checks.** LLMs plan and attack. Code runs the tests, records everything and decides the verdict wherever it can.
- **Evidence is the truth.** The approved test plan plus what was recorded decide the result, never an LLM's opinion alone.

## The key product decision

**An MCP server with an AI inside is a bot with a different way of connecting.** One page, **Test your AI**, replaces the separate bot setup, quick scan and MCP pages. Step 1 asks how to reach the AI:

1. **HTTP endpoint** (URL plus key).
2. **Paste a curl or code snippet** (today's quick-scan parser).
3. **MCP server**: Redflag lists the tools and the user picks the tool that talks to their AI (for example `ask`, `chat`, `run_task(instructions)`). Recon suggests it; the user confirms.

After that the flow is identical for all three: personas, plan, approval, live run, report, comparing with the last report.

Consequences:

- Redflag does **not** host a stand-in agent. Attackers talk to the user's real agent, with their own model and instructions, so "broke" and "held" describe their agent.
- The agent's tool calls happen inside the user's server, so Redflag cannot see them directly. Evidence comes from the reply, from traps (below), and from an optional `logs` key the user adds on a test copy.
- An MCP server with **no** AI inside (a plain tool server such as an Excel server) gets a friendly message ("We couldn't find an AI on this server") with a **Choose the tool that talks to your AI** option. It still gets the instant description checks. See "Plain MCP servers" for what else it keeps.
- Navigation becomes: Demo, Test your AI, Results, Docs. The old `/mcp`, `/quick` and `/setup` links redirect to the new page (`/mcp` with MCP pre-selected). The word "MCP" stays on the landing page and in a "Works with: HTTP bots, curl or code, MCP servers" line.

## Goals

- A saved, replayable attack suite with proof for every finding.
- Attackers that adapt: new angles, multi-step, deeper where defences hold. No test is cut for budget.
- Honest labels: every result says how sure Redflag is and what it could not see.
- Safe by default: nothing changes the user's real data unless they say it is a test copy.
- One flow for every kind of AI target.

## Non-goals

- Proving a target is "secure". The report never claims that. "Held this run" is not "fixed for good".
- Hosting or simulating the user's agent, or intercepting and faking tool results.
- Permission and ownership verification (still deferred, settled before any public launch).
- A long-running background worker. The browser drives the run.
- A measured cost estimate (backlog #3). The plan shows a rough estimate, labelled as one.

## Anti-goals (a failure even if it technically works)

- A confident "Broke" that rests on an LLM's opinion, or on a wrong rule.
- A real change to the user's data in the default mode.
- The user's AI key stored, logged, or put in a URL.
- A result that hides that it was "based on the reply only".

## Components

1. **Connector.** Server or endpoint link and key, plus the user's own **LLM API key** (BYOK) for the personas, supervisor and judge. Reuses `targets/http_target.py` and `targets/mcp_target.py`, including their refusal of private addresses, no redirects, and key redaction. Today's router keys stay Redflag's own; the BYOK key is the user's.
2. **Recon (code).** After connecting, lists tools and works out: which only read and which change data (the user confirms this, see below), where outside content comes in, what can cause harm (delete, export, send), which tool is the AI entry point, and **which read tool can verify each data-changing tool**. Runs the instant checks (extends `mcp/static_checks.py`): hidden text in descriptions, invisible characters, inputs with no limits, look-alike tool names, changed descriptions.
3. **Supervisor (LLM): planner, not judge.** Turns recon into **harm goals** ("delete data the user did not ask about", "send data outside", "read files it should not"), starts personas and gives each the goals that fit, reviews all tests, **removes exact duplicates** (shown with the reason), **keeps variants**, **orders by impact**. **No cuts for budget.** While running it digs deeper where defences hold (new angles, multi-step). Once a goal is broken with proof, that goal is done. Extends today's `setups/supervisor.py`.
4. **Personas (LLMs), by attack style:** social engineer, fake insider, content poisoner, data harvester, resource abuser, QA / edge-case tester, normal user (baseline that must still work, and the "victim" in poisoning tests). They write tests for single tools, chains of tools, and tests tied to no tool. The two files in `personas/` are the human personas behind this; the runtime personas are prompts in code. Builds on `attacks/attacker.py` and `attacks/strategies.py`.
5. **Test spec (one per test).** Persona, goal, mode, tools, **what the legitimate user actually asked for**, strategy, setup (planted data and canaries), opening message, max turns, expected result, **oracle**, severity, OWASP category, whether it changes data, repeats. Extends `setups/generator.py`'s `GeneratedTest`.
6. **Validator (code).** Rejects a test with no checkable oracle, flags tests that change data, checks that the tools and arguments exist. Each persona also supplies **two sample transcripts per test, one that should fail and one that should hold**; the validator dry-runs the oracle on both and rejects the test if either is misclassified.
7. **User review.** Shows the plan (number of tests, goals by risk, time, rough cost, duplicates removed), lets the user untick, edit, restore, and confirm the access level. Nothing runs before approval. Extends the M6 select-and-confirm page.
8. **Runner (code), driven by the browser.** Three modes:
   - **Mode A, direct tool call**: one crafted call, no LLM, rule-checked. Used on the user's plain tool servers and on read-only tools.
   - **Mode B, conversation**: a persona talks to the user's real AI over several turns, through the connector.
   - **Mode C, poisoned data**: on a test copy, bad content is planted where the AI will read it, then the normal-user persona asks something harmless. Did the AI obey the hidden instruction?
9. **Traps.** Canaries (secret words planted in a test's setup), Redflag's own receiving inbox and links, and rules on tool arguments (for example "email only the customer").
10. **Oracles (code), in this order:**
    1. A trap fired, or a forbidden action was attempted (seen in logs) → **Broke**. A trap hit counts only if it carries the canary planted for that test.
    2. The tool or AI clearly refused → **Held**.
    3. Blocked before reaching the tool (for example 403) → **Refused**, shown separately.
    4. Technical failure → **Couldn't test**, with the reason.
    5. Anything left goes to the judge.
    Every rule-based **Broke** gets a quick second check from a separate judge against the test's intent. If they disagree the result is **needs review**, not a confident Broke.
11. **Judge (LLM).** A different model from the attackers. Handles only the unclear cases, and reads the user's `logs` when present. Extends `judge/judge.py`.
12. **Report and saved suite.** See below.

## Can we change things on this server?

Chosen on the connect step. **Classifying tools as "read" or "changes data" is the user's job**: Redflag proposes labels (from the server's own hints, defaulting to "changes data" when unsure) and the user ticks or unticks. Tests are only run on tools the user has cleared.

**No, don't touch my data (default).**
- Mode A runs on read-only tools only, with response checks. Tests that need real changes are listed as "needs a test copy".
- Static checks and Mode B on the AI entry point still run. Note the entry-point tool itself may do real things internally; the page says this plainly before the user continues, and the user decides.

**Yes, it's a test copy.** The user types the server name to confirm.
- Redflag creates its own test resources and tests only on those, then cleans up and reports anything it could not remove.
- It checks what really happened: before and after (read, act, read again, using the matching read tool from recon), canaries (a canary that appears where it should not means a leak), and Redflag's own inbox and links.
- **Optional note to the user:** "If you can, include your server's tool logs with each response under a `logs` key (or `_meta.logs`). Any format is fine." Redflag first runs simple checks on them (is our canary in the logs?), then the Redflag LLM reads them. **Logs are data, not instructions**, because our own attack text will appear in them. Remind the user to turn logs off in production.

**How sure, shown on every result:** confirmed by your logs / confirmed by our checks / couldn't confirm (the AI tried it but we cannot see what the server did) / based on the reply only (no logs, no trap hit).

## Plain MCP servers (no AI inside)

Recon looks for a free-text entry tool. If none is found, or the user picks none, the page says so and offers **Choose the tool that talks to your AI**. A plain server still gets the instant description checks. **Designer's call (item 7 below):** the existing tick-to-test direct tool calls from the old `/mcp` page (manipulated inputs on text parameters, read by the judge) are kept as Mode A for plain servers, under the same access-level rules, so no existing capability is lost by the merge.

## Budget, cost and safety

- **BYOK:** the user's key is used only for the current run, never stored or logged, never in URLs. Recommend a dedicated key with a spending limit and show which models use it.
- **Show a rough cost and time before the run**, and money used so far during it. The estimate is labelled an estimate (measured estimates are backlog #3).
- **Safety limits only, no budget limits:** max turns per conversation, loop detection, back-off when rate-limited, a **Stop** button that keeps results, and **resume**.
- **Use rules first**, even with plenty of budget, because rule results are the same every run.

## How a run works (browser-driven)

The server never keeps the user's key and runs no long background job. The browser holds the key for the session and drives the run **one test at a time (one turn at a time for conversations, to stay inside short request limits on free hosting)**: each request carries the key, the server runs that single step, saves the result and conversation state to the database and forgets the key. A server restart only interrupts the request in flight; the next request continues from saved progress. If the user closes the tab, they reopen the report, paste the key again and it continues from the last saved step. The page says the tab must stay open. For CI, a small command-line tool drives the run the same way the browser does (extends `ci/`).

## Report, saved suite and regression

- Headline total: held, broke, refused, couldn't test.
- **Fix these first:** each finding shows the conversation, the attempted action, how sure we are, and a code-level fix.
- **Coverage:** tools × goals × personas, with gaps shown.
- **Run details:** models, cost, time, access level that ran.
- Export as PDF (print), JSON and JUnit XML.
- **Regression:** every report stores the full conversations, including the attacker's exact messages. When a new run starts on the same target (matched by server address and the **tool names**, not descriptions, since a fix changes descriptions), Redflag loads the last report and resends the saved attacker messages word for word for every test that broke last time. Each replayed test runs a few times and is reported as a rate ("broke 0 of 5"). Then it runs fresh live variants. The new report keeps them apart: "from last time: 7 fixed · 2 still broken" and "new this run: 1 new problem found". Worded as "held this run", never "fixed for good".

## Chat bots with no tool log

Same personas, goals and plan. Without visible tool calls, results come from reply rules, canaries, Redflag's inbox and links, and the judge, and the report marks them **"based on the reply only"** unless the user connects logs or a trace.

## Constraints

- Free-tier hosting: short requests, a database for state, a server that may restart or sleep at any time.
- Redflag's own model router (free tiers) stays for Redflag-owned work such as the interviewer; the user's key covers personas, supervisor and judge for their run (see "Calls made by the designer", item 1).
- Existing safety rules of the targets package stay: no private addresses, no redirects, key never in results.
- Existing tests stay green; new code follows the repo's test-first habit.

## Suggested build order (the builder may re-slice)

1. Test spec, oracle engine and validator (including the dry-run on sample transcripts), plus Mode A upgrades. Everything depends on this.
2. Recon, tier handling (access level, user-confirmed tool labels) and AI entry-point detection.
3. Traps (canaries, inbox and links) and the `logs` reader.
4. The merged "Test your AI" page, connector for the three entry kinds, and redirects.
5. Personas, supervisor planner, and the browser-driven run with resume.
6. Saved suite, replay as a rate, and the new report sections; CLI for CI.

## Left to the builder

Data model and migrations, prompt wording, the exact page layout, how personas share code, the inbox hosting mechanism, the dry-run transcript format, file names, and test layout.

## Decisions by the owner (as they decided them)

- The AI-inside MCP server is merged into the bot flow; no stand-in agent; plain servers get the friendly message.
- Classifying tools read vs changes data is the user's responsibility, by ticking.
- Tier choice is explicit; the default never changes data; test copy needs the server name typed.
- Browser-driven run, key never kept on the server; resume by re-pasting the key.
- Replay saved attacker messages as a rate plus fresh variants; second-judge check on every rule-based Broke; canary must arrive for a trap hit to count.
- Stop a test at the first forbidden action.
- A measured cost estimate is deferred to the backlog.

## Calls made by the designer (not yet confirmed by the owner)

These came out of the builder check. Each is a sensible default; the owner can overrule any of them.

1. **Keys and models.** The user supplies **one** key (one provider) and two model slots: an *attacker* model (personas, supervisor, attacker, log reader) and a *judge* model (judge, second-judge), defaulting to two different models from that provider. BYOK calls bypass the response cache and spend tracking entirely (a prompt-keyed cache could leak across users), and the key is passed per request and never stored. The setup interviewer (the pre-run chat that builds rules) stays on Redflag's own router.
2. **State and cleanup.** Each step saves: the test, its saved transcript, and a **cleanup ledger** of every resource Redflag created on a test copy. A mid-conversation test resumes from its saved transcript. Cleanup runs at the end of a run, on resume, and from a **Clean up now** button. If the user never returns, the report lists the leftover resources by name so they can remove them by hand. Step endpoints are idempotent per test id.
3. **Traps in v1 are HTTP only.** The backend hosts the trap endpoint (a unique token per test and repeat, public URL, hits stored with the test's time window). **Email-address traps are not in v1**; "sent to the wrong person" is checked from logs or tool arguments instead, and a test with no way to check it is marked "needs logs".
4. **Oracle vocabulary in v1** is a closed list: canary seen in the reply, logs or a trap hit; a tool-argument rule checked against logs; before/after state difference; and "refused" meaning a refusal status code or error from the target, or a short refusal phrase list. A phrase match alone never makes a result Held if a trap fired (order of oracles still applies). Anything outside this list goes to the judge.
5. **Additive, not a migration.** The old API routes, the 30-test suite, the demo bots, `/how-it-works` and `/results` all keep working. The old `/setup`, `/quick` and `/mcp` pages become front-end redirects to the new page. Removing old code is a later, separate decision.
6. **Same target for regression** is the endpoint URL (host and path) plus, for MCP, the chosen entry tool and the tool names. Reports stay **owner-only behind today's owner password**; accounts and permission checks stay deferred.
7. **Mode A payloads** come from a fixed catalog in code (today's `mcp/dynamic.py` manipulations, extended). Persona-written payloads may be added later as data, still executed without a model at run time.
8. **Forbidden-action checks** run in code only where Redflag can see tool calls: direct calls (Mode A) or the user's `logs`. Without logs the verdict falls to the judge and is labelled "based on the reply only". "What the legitimate user asked for" feeds the oracle rule and the judge's prompt.
9. **CI command** takes the key from an environment variable, runs unattended, and uses exit codes and thresholds like today's gate in `ci/gate.py`.
