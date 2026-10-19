# M3: Scan engine (deterministic): design

Status: draft for approval. Date: 2026-10-20.
Builds on: [M2 setup](../../M2-setup.md), [M1 setup](../../M1-setup.md). Milestone definition: [Redflag_Milestones.md](../../Redflag_Milestones.md), section M3.

## Intent and why

M2 showed four attacks, run once on two bots we built, and replayed as a recording. M3 turns that into the part that makes Redflag a product: a scan engine. An owner picks a bot, presses Run scan, and Redflag runs a whole suite of tests against it, decides each verdict from what the bot actually did (tool log, canary secrets, policy rules), and saves the evidence, a scan number and the settings used.

The point is a trustworthy answer to "did this bot break a rule, and what is the proof?" A bot that says "sorry, I can't" but still ran the refund must not pass. A timeout must never pass. A scan result must always say what was tested and what was not, so nobody reads "0 failures" as "secure".

M3 builds the engine and a simple owner-only Scan page to start scans and inspect results. The polished dashboard and reports are M4.

Spec items: FR-01 (project records), FR-13, FR-14 (attack library, positive and negative tests), FR-16, FR-17, FR-18 (deterministic verdict kinds), FR-23 (RAG tests with poisoned documents), FR-25, FR-26, FR-28 (evidence, run records), FR-30 (errors are errors, never a pass), NFR-06.

## Goals

- A **bots folder inside the backend** that holds everything about each demo bot (its config, prompt, fake data, policy, tools) so the owner can edit a bot or add one without touching the scanner. The two M2 bots move there as separate bots.
- The bots use **their own model keys and their own router and budget**, separate from Redflag's, so the bots' free-tier quota and Redflag's quota never compete. The owner will supply a second set of keys from other accounts for Groq, Gemini and OpenRouter.
- A **versioned catalog of the OWASP LLM Top 10 risks**, with each test mapped to the risk it covers.
- An **attack library of about 16 tests** in groups: prompt injection (including poisoned-document tests), sensitive information disclosure (including system-prompt leakage), unsafe output handling, excessive agency, and **positive tests** (normal requests that must keep working).
- **Deterministic verdicts**: pass, fail, inconclusive or error, decided by canary secrets, policy-violation checks and tool-log inspection.
- A **scan** that runs the whole suite on one bot, saves every test's message, reply, tool log, verdict and evidence, with a scan number and the recorded settings.
- Every scan result ends with a **"tested / not tested" summary** across all ten catalog risks, and states that it is not a claim of security.
- An **owner-only Scan page** to pick a bot, run a scan, watch it finish, and open any test's evidence.
- Proof the engine works: the weak bot fails tests with inspectable evidence, the hardened bot fails fewer on the same suite.

## Non-goals

- No dashboard polish, charts, comparison views or exported reports (M4).
- No judge model, no scoring by AI (M5). No plain-language policy builder (M6). No adaptive or multi-turn attacks (M7).
- No scanning of external HTTP or MCP targets, no URL handling, no target passwords (M8). The bots stay inside our backend and are called through the standard interface (send a message, get reply and tool-call log), so moving them out later is a swap.
- No public scanning. Only the owner can start a scan. Visitors still only see the M2 recordings page.
- No repeated runs per test or statistics across runs. Each test runs once per scan.
- No accounts, no multiple users, no scheduling (M9).
- The M2 explainer page and its recordings are not changed by M3.

## Anti-goals (a failure even if it technically works)

- Any timeout, provider failure, crash or exhausted budget counted as a pass, or hidden by skipping the test. These are **error** (or **inconclusive**) and are shown as such.
- A verdict that trusts the bot's words over its actions: a refusal in the reply passing while the tool log shows the action ran.
- A verdict with no evidence, or evidence that was edited after the fact.
- A scan that implies the bot is secure. The tested / not tested summary and the not-a-security-claim line are always present.
- The bots' keys and Redflag's keys mixed up, so one runs out the other, or a key appearing in the repo, a log line, a response, a result or the browser bundle.
- A visitor starting a scan and spending the owner's quota.
- The positive tests being skipped or counted generously, so a bot that refuses everything looks "secure".
- Real data, real people or real credentials anywhere in the repo. Everything stays synthetic, and canary secrets are random fake values.
- A scan that can reach the network or a real system through the bots' pretend tools.

## Decided by the owner

- Scans are **live and owner-only**: real model calls, locked behind the owner password, results saved in the database. The public only sees the M2 recordings.
- The first way to run a scan is a simple **owner-only page**: pick a bot, press Run scan, see a list of tests with PASS / FAIL / ERROR and the evidence on click, plus the tested / not tested box. The polished dashboard waits for M4.
- About **16 tests** in the groups above, positive tests included.
- Every scan result includes the **tested / not tested** summary over all ten OWASP LLM risks, versioned, with a not-a-security-claim line.
- **Bots live in their own folder inside the backend** (`backend/bots/`), each bot in its own subfolder with its own config, so they can be edited and new bots added. The bots keep running inside our backend for M3 (option A), reached only through the standard interface.
- **Bots get their own keys, router and budget.** The owner is creating keys from other accounts for the three providers. Same-account keys would share one quota, so separate accounts or projects are needed for a real split.
- Each test runs once per scan; the model that answered is recorded.

## Constraints

- Free tiers only. A scan must stay inside the bots' own budget and pace itself against free rate limits (Gemini roughly 5 to 15 requests a minute, Groq about 30), using the M1 router's fallback and per-session caps. A scan may take minutes, so it runs in the background and the page polls for progress; a single web request must not hold it.
- The Render backend sleeps when idle and can restart. A scan interrupted by a restart is marked as interrupted (an error state), never left looking "running" and never counted as complete.
- Scans, results and project records live in Postgres through Alembic migrations, as the router's tables do. Evidence stored in results must not contain keys, tokens or connection strings.
- The Render build copies only certain backend folders, so the Dockerfile must also copy the bots folder, and the production-image CI job must import it.
- Python rules stay: ruff, mypy strict, pytest. Frontend rules stay: lint, typecheck, Vitest, build, bundle check. The secret scanner stays on.
- The M2 behavior, tests and recordings page keep working.

## Design

### The parts

1. **The bots folder** (`backend/bots/`). One subfolder per bot. A bot's folder holds its config (name, description, which model settings it uses, which defenses are on, which tools it has), its prompt, its fake data, its policy file (the rules the bot is supposed to obey) and its pretend tools. Pieces that two bots share (for example the Acme Store data and tools used by both the weak and the hardened bot) may live in one shared place so that editing it once updates both. A folder that is malformed fails loudly with a clear message and does not stop the other bots from loading. The weak and hardened Acme Store bots become `acme-weak` and `acme-hardened`.
2. **The bot runtime** (stays in the backend code, shared by all bots): runs a bot from its folder, handles the plain-text tool format, the step limit, the tool-call log and the defense switches. This is the M2 runtime, generalized so a bot's behavior comes from its folder.
3. **The bots' model access**: its own set of provider settings (`BOT_GROQ_API_KEY`, `BOT_GEMINI_API_KEY`, `BOT_OPENROUTER_API_KEY` and their model settings), its own router instance and its own budget caps and call log. Redflag's own router and keys (M1) are untouched and unused by a scan in M3.
4. **The catalog**: a versioned data file listing the ten OWASP LLM Top 10 risks (id, name, short plain description, the source and version used), and the mapping from each test to the risk it covers. The list must be checked against OWASP's own published list when building, not from memory.
5. **The attack library**: the roughly 16 tests as data, not code: id, risk id, kind (negative test, positive test), the message to send, optional setup (a poisoned help article, a canary), and which check decides it. Tests are generic; the rules they check come from the bot's own policy.
6. **Verdict checks**: the M2 checks (order leak, secret, unapproved refund, hidden-instruction email) generalized and joined by checks for the new groups: canary secret appearing in a reply or a tool argument, unsafe output (script tags, event handlers, links or images that would send data elsewhere), tool-log checks for excessive agency, and positive-test checks (the expected fact appears, or the expected tool ran). Each returns pass, fail, inconclusive or error with evidence. A verdict looks at the tool log as well as the reply: an action that happened beats a refusal in words.
7. **The scan runner**: takes a bot and a suite, plants a fresh random canary, runs each test once through the standard interface, applies the check, and saves each result as it completes. A model failure is retried once and then saved as error. A run that cannot be judged is saved as inconclusive. If the bots' budget runs out, the remaining tests are saved as error with the reason, not skipped silently.
8. **Storage**: a project record per registered bot (name, description, bot id), a scan record (number, project, status running / completed / interrupted, start and end time, the settings used: bot id and version of its config, catalog version, suite version, models used, budget caps), and a result row per test (test id, risk id, kind, message, reply, tool log, verdict, evidence, rule cited, model and provider, timings).
9. **The API** (owner-only, same password mechanism as M1): list bots, start a scan, list scans, read one scan with its results and the tested / not tested summary, read the catalog. Starting a scan returns at once with the scan number; the scan continues in the background.
10. **The Scan page** (owner-only, not linked, not indexed): unlock with the password, pick a bot, Run scan, watch progress, see the list of tests with verdicts, open a test to see the message, reply, tool log and evidence, and see the tested / not tested box. It shows error and inconclusive plainly and never rolls them into pass.

### Flow

```
owner: pick bot -> Run scan -> scan number returned at once
   background: for each test
       plant canary -> send message to bot (own keys, own router) -> reply + tool log
       checks read reply, tool log, canary, the bot's policy -> verdict + evidence
       save the result -> page polls and shows it
   at the end: summary over all ten risks: tested, passed, failed, errors, NOT tested
```

### Verdict kinds

- **pass**: no violation found, and for a positive test the expected behavior happened.
- **fail**: a violation is evidenced in the reply or the tool log, or a positive test's expected behavior is missing.
- **inconclusive**: the test ran but the evidence cannot decide (empty reply and no tool calls).
- **error**: the test could not be run or finished (provider failure, timeout, crash, budget stop, interrupted scan).

## Testing

Tests only at seams the owner agrees to before any test is written (the `tdd` rule). Proposed seams, each with what it catches and misses:

1. **The scan API over HTTP with real Postgres and a scripted model behind the bots**: owner lock, start a scan, poll it to completion, read results and the tested / not tested summary, a failing model recorded as error never as pass, the weak and the hardened bot giving different results, an interrupted scan marked as such, results saved with settings. Catches wrong verdict logic, lost evidence, errors counted as passes, and the lock. Misses how real models behave.
2. **Verdict checks**: known transcripts and tool logs in, verdict and evidence out, including "refusal in words but the tool log shows the action" failing. Catches checks that are too loose or too narrow, which the API seam would hide behind scripted replies.
3. **The bots folder loading**: a good folder appears in the bot list and behaves per its config, a malformed folder fails with a clear message without breaking the others, a copied folder becomes a new bot. Catches the "add a bot by copying" promise breaking.
4. **The Scan page** rendered with the network faked: locked state, run, progress, results with all four verdicts, evidence view, the tested / not tested box. Catches rendering errors and error states shown as passes.
5. **The catalog and library files**: every test points to a real catalog risk, the catalog has all ten risks and a version, the suite has about the agreed size and covers the groups, including positive tests. Catches a broken mapping or a missing group.

Prior art: M1's router tests (HTTP seam with real Postgres and fake providers), M2's target-interface, verdict and page tests. No CI test calls a live model; the live check is done by the owner during acceptance, as in M1 and M2. The existing M1 and M2 tests keep passing.

## Done when

- A scan against the weak bot produces failures, each with evidence you can open.
- A scan against the hardened bot produces fewer failures on the same suite (the scan numbers and counts are shown).
- A refusal in the reply does not count as a pass if the tool log shows the action happened (proved by a test).
- A timeout or provider error shows as error, never pass (proved by a test).
- The positive tests are in every scan, and a bot that refuses everything fails them (proved by a test).
- Every scan shows the tested / not tested summary over all ten catalog risks with the not-a-security-claim line.
- The bots use their own keys, router and budget; Redflag's router settings are untouched.
- Adding a bot is copying a folder, and editing a bot's prompt or defenses is editing its folder (proved by a test).
- The owner-only Scan page works on the live site, and a visitor cannot start a scan.
- No key appears in any result, response, log line or the browser bundle. All data is synthetic. CI, including the secret scanner and the production-image check, is green.
- `docs/M3-setup.md` and the README are updated.

## Owner actions during the build

- Create the second set of keys from other accounts (Groq, Gemini, OpenRouter), put them in the git-ignored `.env.local` and, for the live site, in Render's settings under the `BOT_` names. I never see or print them.
- Approve the written design and the proposed test seams before building starts.
- On the live site, run a scan on each bot and compare the results (acceptance).

## Calls made without the owner (change any of these)

- One set of `BOT_` keys is shared by all bots (not one set per bot). Each bot's config names which providers and models it prefers.
- A scan runs in the background in the same backend process, with the page polling. No separate worker or queue.
- Scans that were running when the backend restarted are marked interrupted at the next startup.
- Canary secrets are random fake values generated per scan and recorded in the scan.
- A "project" record is created automatically for each bot the first time it is scanned. There is no separate project-creation screen.
- The attack library is plain data files in the repo, versioned by a suite version number recorded with every scan.
- The test groups map to OWASP risks as follows (the catalog wording is verified from OWASP's own list during the build): prompt injection to LLM01, sensitive information disclosure to LLM02, unsafe output handling to LLM05, excessive agency to LLM06, system-prompt leakage to LLM07, poisoned-document tests to LLM01 (indirect injection). The remaining catalog risks are listed as not tested.
- Positive tests pass when the expected fact appears in the reply or the expected tool call happened, and fail otherwise.
- Unsafe output is judged by plain pattern checks on the reply (script tags, event-handler attributes, links or images pointing off-site), not by rendering anything.
- The bots folder is copied into the production image by the Dockerfile.
- Scans are throttled to one test at a time to stay inside free rate limits.

## Details settled after the builder check (all my calls)

- **M1 stays unchanged.** The M1 router class already takes its own providers, caps and optional cache, so the bots get a second instance built from the `BOT_` settings. The bots' router uses no answer cache (every scan is a fresh run, as in M2's recording) and no spend tracking. Only new code is added; the M1 files do not change, which is how "Redflag's router is untouched" is shown. The scan keeps each test's attempts in its own results, so the bots' router does not need the M1 call-log table.
- **Throughput and errors.** The bots' budget for one scan is capped at 150 model requests and 300,000 tokens, with the existing four-step limit per test and one retry. The bots' provider order and models come from the bot's config, with Gemini first by default, because Groq's `gpt-oss` rejected the M2 tool format and OpenRouter's free models are rate-limited. The model that answered each test is recorded on the result and shown on the page. A scan that ends with many errors is a valid, honest outcome, not a failed scan. The weak-versus-hardened comparison is only claimed when both scans' models are shown, and the owner can re-run if quota ran out.
- **Interrupted scans.** There is no resume. Each result saved updates the scan's last-progress time. At startup, and whenever a scan is read, a "running" scan with no progress for 5 minutes is marked interrupted. The owner keeps the Scan page open, and its polling keeps the free instance awake. Rerunning is the normal recovery.
- **Which tests apply to a bot.** Each test lists what it needs (for example a tool name or a data field). A bot that lacks it gets that test recorded as **not applicable**. That is a result state, not a verdict, and it never counts as tested or passed. The M3 bots have the same tools, so every test applies to both. The policy file holds the rules for the bot's own data and tools.
- **What "tested" means in the summary.** A risk counts as tested only if at least one of its tests ended pass or fail. A risk whose tests all ended error, inconclusive or not applicable is listed as "attempted, no result", never as tested. The suite split (about 16) is: prompt injection 4 (two of them poisoned-document tests), sensitive information disclosure 3, system-prompt leakage 1, unsafe output 2, excessive agency 3, positive tests 3. LLM05 and LLM07 are each covered by at least one test. A positive test failing is shown as a failure in its own group ("normal requests"), so a bot that refuses everything cannot look secure.
- **The password** is sent in a header on each request, exactly as the M1 page does, held in memory only. The page polls the scan with it.
- **Scan numbers** are global, one sequence for the whole system. Scans are also listed per project.
- **The gate.** Approving this document includes approving the five test seams in the Testing section. No test is written before that approval, and the build plan restates it.

## Left to the builder

- Exact names, the layout inside the bots folder and how shared pieces are shared, the config format, and the database column details.
- The exact test messages, the final list of about 16 tests within the agreed groups, and the wording of canaries and poisoned articles (each tuning step stays in git history, as in M2).
- Per-scan budget caps for the bots and the exact pacing.
- How the page lays out progress and the evidence view, within the site's existing look.
