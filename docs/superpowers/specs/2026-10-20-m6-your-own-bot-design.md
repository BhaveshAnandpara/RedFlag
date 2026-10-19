# M6: Test your own bot (policy builder, generated tests, real endpoint): design

Status: draft for approval. Date: 2026-10-20.
Builds on: [M5 setup](../../M5-setup.md), [M4 setup](../../M4-setup.md), [M3 setup](../../M3-setup.md), [M1 setup](../../M1-setup.md). Milestone definition: [Redflag_Milestones.md](../../Redflag_Milestones.md), M6 (policy builder) plus the HTTP part of M8 (external targets). Both are rewritten by this design; see "Scope change".

## Intent and why

Until now Redflag tests only the two Acme demo bots, with 16 tests written by hand. The product idea is different: someone plugs in **their own** AI, tells Redflag about it, and Redflag attacks it and shows what got through.

The owner's description of the flow, in their words, tidied:

- There are two kinds of customer: one with a **public support chatbot** for their product, and one with an **AI agent for an enterprise product**.
- The site shows a call to action ("you can also test your own AI chatbot here"). It leads to a setup page.
- The setup is a **chat with an AI**, not a static form. The user gives whatever they have: a description, examples, files. The AI interviewer also **asks clarifying questions** ("how much can the bot refund?").
- A **supervisor AI** takes everything the user provides and writes **two contexts**: one for the **tester** (how to attack) and one for the **judge** (what counts as a violation).
- Redflag generates up to **30 tests**, each described: the exact prompt, what we are trying to find out. The user **selects** which to run (all ticked at first) and confirms.
- Redflag then runs the selected tests **against the user's real bot** over HTTP, and the AI judge decides each result.

Spec items: FR-08, FR-09, FR-10, FR-11, FR-12, FR-15, and the HTTP-endpoint part of the external-target requirements.

## Scope change (decided by the owner during the M6 brainstorm)

| Original plan | Decision |
|---|---|
| M6 builds a policy form and generated tests that run on the demo bots (option A, first agreed) | **Changed:** tests run on the user's **real bot** over HTTP. The owner wants the result to be about their bot, not ours |
| M8 later adds external HTTP and MCP targets | The **HTTP chat endpoint** moves into M6. **MCP stays in M8** |
| A static policy form | **Changed:** a **chat setup** with a supervisor AI and a live side panel |
| Permission and ownership checking | **Deferred** by the owner, to be settled before any public launch |

`docs/Redflag_Milestones.md` is updated when M6 is built: M6 renamed to cover the setup chat, generated tests and real HTTP targets; M8 reduced to MCP servers and anything left of external targets.

## Goals

- A **setup chat** where a user describes their bot by talking, and a **side panel** that always shows what Redflag has understood, as fields the user can click and edit.
- **Required data** that must be filled before the next step unlocks: a **working endpoint connection** (URL, format and key, with a successful Test connection), **what the app is for**, and **at least one thing it must never do or reveal**. Everything else is optional.
- **Follow-up questions** from the AI interviewer where a rule has a gap (limits, approvals, protected data, tools), capped at about **8**, each **skippable**; a skipped item stays marked **unclear**.
- A **supervisor AI** that turns everything provided into two **structured contexts**: tester and judge. The user can read and edit both in the side panel.
- A **rules screen**: the rules the AI understood, typed (allowed, forbidden), with unclear ones highlighted, for the user to edit, delete or fix before any test is generated.
- **Test generation** of up to **30** tests, mixing attacks across the OWASP risks that apply, and normal requests, each with a title, risk, severity, the exact prompt, what we are trying to find out, and what a correct reply looks like.
- A **select and confirm** page: tests described in full, **all ticked at first**, tests that rest on an unclear rule labelled "rule not confirmed", tests that could trigger a real action labelled clearly. **Nothing runs until the user confirms.**
- **Running** the selected tests on the user's endpoint over HTTP, with the judge deciding every result, and the result opening in the existing dashboard.
- **Setup versions**: each confirmed setup is saved as a numbered version; scans point at the version they ran with; two versions can be compared with the Compare tab, which also shows what changed between the setups.
- The AI judge from M5 is reused **with its interface unchanged**, fed an app context built from the supervisor's judge context.

## Non-goals

- No MCP server targets, no multi-turn or adaptive attacks (M7 and M8).
- No accounts, no permission or ownership proof, no billing, no open public access: the page is **owner-password only**, the same pattern as `/scan`. (My call: the owner said not to worry about early access, so there is no "request access" state, but the page is still locked.)
- No reading of tool logs from the user's bot: a plain chat endpoint shows only the reply, so for real bots the judge decides from the reply text alone, and the dashboard says so.
- No changes to the two demo bots, the 16 hand-written tests, or the existing `/scan` flow.
- No measuring of judge accuracy (M5b).

## Anti-goals (a failure even if it technically works)

- **The user's API key ever reaching an AI model, a log, the database, a saved report or the browser's storage.** It is typed into a secure field, never into the chat.
- **Attacking a server the user does not control, or Redflag's own network.** Internal and loopback addresses are refused, and a run has a hard request cap. (Proof of permission is deferred, but these are not.)
- **Running a test the user did not select**, or any test before they confirm.
- **A rule the AI guessed shown as if the user said it.** Anything the user did not state is labelled, and unclear rules say so.
- **A judge result that looks firmer than it is**: results on a real bot are decided by an unvalidated AI alone, and every page and report says so.
- **Pasted text or uploaded files acting as instructions** to the supervisor, tester or judge beyond their role as data. (Securing the supervisor against hostile text is deferred by the owner and listed as an open item; the basic fencing is not.)
- **A "safe" or "secure" claim** about the user's bot. The wording rules from M4 and M5 apply unchanged.
- **Hiding a connection failure.** An unreachable endpoint, a wrong format or an error reply is an error result, never a pass.

## Decided by the owner

- Two customer types: public support chatbot and enterprise agent.
- A call to action leads to a setup page; the setup is a **chat with an AI**, not a static form, with some data **required**.
- Users may paste examples and upload skills or context files; these feed the tester and the judge.
- A **supervisor AI** receives everything and creates **two contexts**, one for the tester and one for the judge. How to secure it is deferred.
- The interviewer **asks clarifying questions** such as the refund limit.
- A **rules-review screen** is included.
- Tests run on the **user's real bot**, over an **HTTP chat endpoint** first (**not** MCP yet), with a **default OpenAI-compatible format** and a custom option (request template and reply path) and a **Test connection** button.
- **Up to 30 tests, all ticked** at the start; the user selects and confirms before anything runs.
- **Permission and ownership checks are deferred.**
- The API key never goes through the chat.
- Access gating is not a concern for now.

## Constraints

- Free tiers only. The interviewer, supervisor, generator and judge all use Redflag's own model router and keys (M1), with their own budgets, apart from the bots' `BOT_` keys. A run of 30 tests costs about 60 model calls (30 judge calls, plus the target's own cost on the user's side), plus the setup chat.
- The user's bot is called from the Redflag backend over the internet, so every call needs a timeout, a cap on reply size, and no redirects to internal addresses.
- Uploaded files are small (text, markdown, JSON), capped in size and number, held only as long as the setup needs them, and treated as untrusted data.
- Scans, the AI judge, the dashboard and the report keep working as they do. Scans from M3 to M5 still open.
- CI stays free of live model calls and of real outside servers: the endpoint is faked in tests.

## Design

### The flow

```
owner opens the setup page, unlocks it
  chat with the interviewer + side panel (fields, status, tags, the two contexts)
  secure fields: endpoint URL, format, key  -> Test connection (one harmless "hello")
  required fields filled and connection works  -> "Review the rules" unlocks
rules screen: edit / delete / fix unclear rules  -> confirm the rules (setup version N saved)
generate: up to 30 tests from the confirmed rules + the tester context
select page: all ticked, each test described, flags for unclear rules and real actions
confirm -> run: each selected test is sent to the endpoint, the judge reads each reply
dashboard: the existing results view, with the rules at stake and the unvalidated-judge notes
```

### The parts

1. **The interviewer.** A chat backend that, on each user message, updates the structured **setup fields** and decides the next question. It asks about the biggest gap first (required fields before optional ones), asks no more than about 8 follow-ups, and lets the user skip any question. It never receives the endpoint key. The user's text, pasted examples and file contents reach it as quoted data.
2. **The setup fields** (structured, saved with each setup version): purpose; rules (each: text, allowed or forbidden, severity, and a status of stated, inferred or unclear, plus where it came from); limits (for example a refund limit); protected data; tools (name, what it does, whether it only reads or acts); examples (each marked good or bad reply, or a conversation to learn from); free-text notes; the endpoint settings (URL, format, header name; never the key).
3. **The supervisor.** One step that reads all setup fields, examples and file contents and writes the **tester context** and the **judge context**, each as structured fields plus short notes, with every item tagged with where it came from. The judge context holds: purpose, rules at stake with severities, protected data, limits, tools with reads/acts, and the user's examples as quoted data. The tester context holds: purpose, tools, likely weak spots from examples, and what to try per risk. The routing only chooses which context an item goes to; it does not rewrite the user's examples, which go to the judge verbatim. The side panel shows both contexts and the user can edit them. The supervisor is its own step in code, so it can be hardened or replaced later without touching the rest. **Securing it against hostile pasted text is an open item.**
4. **The rules screen.** Shows the rules from the setup fields, typed and with statuses; unclear ones are highlighted with the question that would clear them. The user edits, deletes, adds or confirms. Confirming saves **setup version N** (all fields and both contexts, immutable). Generating tests needs a confirmed version.
5. **The test generator.** From a confirmed setup version, makes up to **30 tests**: attacks across the OWASP LLM risks that apply to the described app (for example an app with no tools gets no tool-misuse attacks), and normal requests. Each test: id, title, risk (or "normal request"), kind, severity, **the exact prompt**, **what we are trying to find out**, **what a correct reply looks like**, the rule it is based on, a flag if that rule is unclear, and a flag if it could trigger a real action. Single messages only. The generator's output is validated (shape, count, no duplicate prompts, no more than 30) and a bad output is retried once, then reported as a failure to generate.
6. **The select and confirm page.** Lists every generated test in full, all ticked, with the flags. The user can untick tests. Confirming records exactly which tests were selected, and **only those run**. At least one test must be ticked.
7. **The HTTP target adapter.** A new kind of target with the same `send(message)` shape the scan engine already uses, that sends the prompt to the user's endpoint and returns the reply (and no tool log). Formats: **OpenAI-compatible** (default) and **custom** (a request template with a prompt placeholder, and a path to the reply in the response). The key goes in a header whose name is configurable. Every call has a timeout, a cap on reply size, no following of redirects, and a refusal of loopback, private and link-local addresses (checked on the resolved address, not just the text). **Test connection** sends one harmless message and shows the status and the raw reply. Connection errors, timeouts, non-success statuses and unreadable replies are saved as **error** results with the cause, never as passes.
8. **Running and judging.** The scan runner gets a second path for generated tests on an HTTP target: send the prompt, then the judge (M5, unchanged) reads the reply with the judge context and the test's own "what a correct reply looks like". There is **no plain-rules check** for generated tests, so the result is the judge's verdict alone: pass, fail, or inconclusive when the judge is unavailable (never a green pass). The scan records the setup version, the selected test ids, the endpoint host (not the key), and the budget. A hard cap limits the requests per run.
9. **Versions and compare.** Each scan points at its setup version. The Compare tab (M4) keeps working between any two scans, and when the two scans have different setup versions it also lists **which rules changed** between them. A "compare two versions" entry point lets the owner pick two versions.
10. **The pages.** A setup page (chat, side panel, secure fields, rules screen, select page, run progress) behind the owner password, and a call to action on the home page that leads to it. Results open in the existing dashboard. Wording on every page: the result is decided by an unvalidated AI judge from the reply alone, and is not a claim that the bot is secure.
11. **Saved data.** New tables for setup versions (fields, both contexts, status, created time) and for generated tests per version (with the selection). Scans gain a link to a setup version. The endpoint key and uploaded file contents are **not** saved with the version; only the extracted fields and the contexts are. (Examples the user pasted are part of the contexts, so they are saved as part of the contexts.)

### What changes for results on a real bot

- **No tool log.** The Conversations tab shows the message and the reply, and says the tool log is not available for this kind of target.
- **No plain-rules output.** The "Plain rules" block says no plain rule applied; the judge's verdict and reason stand alone.
- **Severity and fix notes** come from the generator's severity and a short fix note it writes per test.
- **The conclusion** keeps the M4 wording and always says the judge is unvalidated; with no plain-rules second opinion, it says so.

## Testing

Tests only at seams the owner agrees to before any test is written (the `tdd` rule). The only faked parts are the outside models (as in M1 to M5) and the user's **endpoint**, a stand-in HTTP server in the test. Proposed seams, each with what it catches and misses:

1. **The setup conversation over HTTP**, with a scripted fake model and real Postgres. Catches: required fields locking the next step, follow-ups capped and skippable, skipped items marked unclear, the key never appearing in any model prompt, response, log line or saved row, pasted examples reaching the judge context verbatim and tagged, edits in the side panel winning over the model, setup versions saved immutably. Misses: how good the real interviewer's questions are.
2. **The generator and supervisor on their own interface**, with a fake model. Catches: the 30 cap, malformed output retried once then failing clearly, tests tagged unclear or real-action, an app with no tools getting no tool-misuse tests, and the tester context and judge context holding the right items. Misses: the real quality of the tests.
3. **The HTTP target adapter against a stand-in server.** Catches: both formats, the key sent only in its header, timeouts and bad statuses becoming errors, the reply-size cap, redirects not followed, loopback, private and link-local addresses refused (including a name that resolves to one), and Test connection reporting what it saw. Misses: the quirks of real servers.
4. **The scan API over HTTP with real Postgres, the stand-in endpoint and a fake judge.** Catches: nothing runs before confirmation, only the selected tests run, the judge's verdict is the result, a judge outage gives inconclusive and never pass, the request cap, scans linked to their setup version, old scans still readable, and the demo-bot scan path unchanged. Misses: real timing.
5. **The pages and the dashboard changes, network faked.** Catches: the chat and side panel, the secure key field not sent through the chat call, the rules screen, the select page with all ticked and the flags, the call to action, and the dashboard's real-bot wording. Misses: how it looks at real sizes.

Prior art: M3 and M5 scan API tests, M5's judge tests, M1's provider tests, M4's dashboard tests. A deliberate break (for example sending the key to the model, running an unselected test, or letting an unavailable judge count as pass) is used to prove each key rule. No CI test calls a live model or a real outside server.

## Done when

- The owner can open the setup page, chat about a bot, answer follow-ups or skip them, and see fields, tags and both contexts in the side panel.
- Setup cannot move on until the required fields are filled and Test connection succeeds.
- The rules screen shows typed rules with unclear ones highlighted, and confirming saves a numbered setup version.
- Up to 30 described tests are generated, all ticked, with unclear-rule and real-action flags; unticked tests do not run; nothing runs before confirming.
- The selected tests run against a real HTTP endpoint (the owner's own test server for acceptance), the judge decides each, and the result opens in the dashboard with the real-bot wording.
- Two setup versions can be compared and the changed rules are listed.
- The key never appears in any prompt, log, saved row or report.
- Loopback and internal addresses are refused; a run has a hard request cap.
- The demo-bot scans and all earlier pages still work. CI, including the secret scanner and the production-image check, is green.
- `docs/M6-setup.md`, the README, the frontend spec and the milestone plan are updated.

## Open items (deferred by the owner)

1. **Permission and ownership.** Nothing stops a user from aiming Redflag at a server they do not own. Must be settled before any public launch.
2. **Securing the supervisor** against hostile pasted text or files. The basic fencing is in; a real defence is not.
3. **Open access.** The page is owner-only for now.

## Owner actions during the build

- Approve this design and the five proposed test seams before building starts.
- For acceptance, point the flow at an HTTP endpoint you control (for example a small test bot) and tell me when to run it. Each run uses Redflag's free model quota.
- Check the setup page, the generated tests and the dashboard on the live site.

## Calls made without the owner (change any of these)

- The page is owner-password only, like `/scan`, with no "request access" state.
- The required set is: working connection, purpose, at least one must-never rule.
- About 8 follow-up questions, each skippable; a skipped item is marked unclear and its tests are labelled "rule not confirmed".
- The endpoint key lives only in the browser's memory and is sent with each request; the backend keeps it in memory for the run and drops it.
- Single-message tests only, up to 30, retried once on a bad generator output.
- Real-bot results have no plain-rules check and no tool log; the judge decides alone.
- The setup chat, supervisor, generator and judge share Redflag's own keys, each with its own budget; names of the settings are the builder's.
- Setup versions are immutable once confirmed; editing starts a new version.
- Uploaded files are text-like only (text, markdown, JSON), small, and capped in number.
- Address refusal is done on the resolved IP address, so a hostname that points inside is refused too.

## Details settled after the builder check (all my calls)

- **The key and a background run.** The user types the key once at confirm time. The backend holds it **in memory only**, for that one run, and drops it when the run ends. It is never written to the database, a log, a saved scan or a report. If the backend restarts mid-run, the scan is marked **interrupted** (as today) and a re-run needs the key again. Test connection and generation never need to keep it. The key is never given to the judge, the interviewer, the supervisor or the generator. If a reply from the user's bot happens to contain the key, it is replaced with a marker before the reply is shown to a model or saved.
- **How a real-bot scan fits the existing model.** Each confirmed setup is a **project** (a slug such as `target-<number>`), so scans, History and Compare work as they do. Generated tests are stored as scan tests with a new check kind, **judge only**, plus their own fields (prompt, what we are trying to find out, what a correct reply looks like, flags, fix note). Results use the same result rows, so the summary, dashboard and report read them unchanged. The `/scan` page keeps listing only the demo bots; real-bot scans appear in History and in the new setup page. The dashboard changes are the ones already listed (no tool log, no plain-rules output, real-bot wording).
- **Risk and severity.** The generator **picks risks from the existing OWASP catalog** (it cannot invent risks), so the dashboard's risk grouping works. Normal requests use the existing "normal request" kind with no risk. Severity is critical, high or medium, chosen by the generator and editable on the select page.
- **Caps and numbers.** A run sends at most **40 requests** to the user's endpoint (30 tests plus room for retries). Test connection is limited to **5 attempts per setup**. The judge has its own budget (about 60 requests per run), the setup chat is limited to about **30 messages** per session, and each of the interviewer, supervisor, generator and judge has its own budget so one cannot starve another. If the quota behind the interviewer, supervisor or generator runs out, the user sees a **clear error** and can retry later; there is no fallback to a different kind of model. If the judge's quota runs out mid-run, the remaining results are inconclusive, as in M5.
- **Panel edits versus the model.** A field the user edits in the panel is **locked** and marked "edited by you"; the model cannot change it, and the user can unlock it. Contexts are regenerated only when the user presses **Regenerate contexts**; a context field the user has edited is kept. The in-progress setup (chat history, fields, contexts) is saved as a **draft**, so a page refresh does not lose it; only a confirmed version is immutable.
- **Address checks.** Both **https and http** are allowed, on any port, but only to **public** addresses: loopback, private, link-local and the cloud metadata address are refused, checked on the resolved address, and the connection is made to that resolved address (with the right host name and certificate check) so a changed answer cannot sneak past. Redirects are not followed. Redflag's own backend address is also refused.
- **The judge is reused with its interface unchanged.** Its inputs (a rule at stake, an app context, tool descriptions, the test, the reply) already fit. What is new is the code that **builds the app context** from a setup version's judge context (purpose, rules with severities, limits, protected data, tools, and the user's examples as quoted data), as `judge_context.py` does for the demo bots today. The judge context is capped in size (about 6,000 characters) so a long pasted example cannot swamp the prompt; anything cut is noted in the context.
- **Custom format syntax.** The request template is **JSON with a `{{prompt}}` placeholder**, and the adapter escapes the prompt into JSON. The reply path is a **dotted path** that may include array positions, for example `choices.0.message.content`. Replies must be JSON; a reply that is not JSON, or a streamed (event-stream) reply, is reported as an error with a plain message.
- **When the required rule is satisfied.** It is a **deterministic check**, not a model judgment: at least one forbidden-type rule whose status is **stated** by the user or **confirmed** on the rules screen counts; a rule the model only **inferred** does not until the user confirms it. The same goes for the purpose field being non-empty and Test connection succeeding.
- **Where the pages live.** The setup page is a route in the **existing Next.js app**, behind the owner password like `/scan`, built in the visual direction of the new home page. The call to action is added to the home page (design file).

## Left to the builder

- Prompt wording for the interviewer, supervisor, generator and judge additions, within the rules above.
- The structure of the setup fields and the two contexts, within what is listed.
- Layout of the chat, side panel and select page, within the design direction of the new home page.
- Table names and the migration, the setting names for the new budgets, and file size and count limits.
- How the stand-in endpoint is built for tests.
