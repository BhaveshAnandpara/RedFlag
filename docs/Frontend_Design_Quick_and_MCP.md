# Frontend design brief: Quick scan (`/quick`) and MCP check (`/mcp`)

As built on 2026-10-20. Written for whoever is designing these two pages. It describes what exists, what each state shows, the exact words used, and the rules the design must keep. It is not a plan for new features. Related: [Wave 2 setup](Wave2-setup.md) · [Frontend spec](Frontend_Spec.md).

> **Update: the owner password is gone from these two pages.** `/quick` and `/mcp` have no unlock step any more: they open straight on the form. The backend only accepts that when the setting `OPEN_QUICK_AND_MCP=true` is on; if it is off, a call is refused and the page says "This tool is not open yet. Please try again later." In open mode only these calls are open: the rule list, the hello check, the MCP tool listing, starting a scan, and reading back the scan you started, using a secret **view key** that starting it returns (kept only in the page's memory, never shown). Everything else (other pages, scan history, Run again, CI tokens, Label mode, judge accuracy) stays behind the owner password, so **the finished view on these two pages is the dashboard only**: no Run again, no CI panel, no label buttons, no "Tailor these tests" link, no history. Sections 2, 3 and 4 below describe the earlier locked version where they mention a locked state, Run again, CI or Tailor these tests; ignore those parts for the open pages.

Both pages are not linked from any menu except the home page, and are kept out of search engines (`robots: noindex`). Today they use plain styles: bordered boxes, one dark primary button, small bordered secondary buttons. Everything below is about content, states and behaviour, not about how it should look.

## 1. Rules the design must keep

- **Never say "safe" or "secure".** A result says what was checked. Reports and banners always end: "This is not a guarantee of security. It only reports what these tests checked."
- **Three kinds of outcome stay visibly different:** passed, failed, and unclear (inconclusive, error, judge unavailable). Untested is a fourth, grey state. Colour is never the only signal; every badge carries its word.
- **The access key is a secret.** It is always a password-type field, lives only in the page's memory, is sent only with the hello check or tool listing and with the run, is never shown back, never stored, and is gone when the page reloads. Nothing on screen may display it (the paste reader names what it found, never the value).
- **The AI judge is always described as "not checked for accuracy"** unless the owner has labeled results (then the accuracy panel shows the numbers and the sample size).
- **Nothing runs without a deliberate click.** MCP tools are only called if ticked; a tool that changes things needs the sandbox box.
- **One scan at a time.** A second start returns "A scan is already running."
- **Plain words for every failure.** Never raw server text or stack traces.

## 2. Pieces shared by both pages

**Locked state.** Heading, then: "Locked: enter the owner password to use this page." A password field labelled "Owner password" and an **Unlock** button. A wrong password shows, as an alert: "That password was not accepted." Nothing else on the page is shown until unlocked. (Used by the owner-only pages. `/quick` and `/mcp` no longer have it.)

**Alert line.** One line of text (`role="alert"`) near the top of the form area for errors. Only one at a time. Cleared when the next action starts.

**Status line.** Small text (`role="status"`) directly under the control that caused it: the paste reader's result, a failed hello, "check the address".

**Running view** (after a run starts, while it is not finished):
- Heading "Scan #N"
- The target's name and "Status: running"
- Progress: "N of M tests done". For an MCP scan the total is unknown, so it says "N tests done so far".
- A list of results so far: a status badge and the test title, appearing one by one.

**Finished-scan view** (when the run ends). Stacked, in this order:
1. **Run these tests again** (quick scan only): explanation, a password field "API key for the run", and a **Run again** button. Hidden for MCP scans.
2. **Use this in your builds** (quick scan only): CI token panel. Token name field (default "github"), **Create an API token** (the token is shown once), a copyable GitHub workflow snippet, the command-line form, existing tokens with revoke. Hidden for MCP scans.
3. **The dashboard** (section 5).
4. Quick scan only, below everything: "Saved as setup #N. **Tailor these tests** to your bot by describing it in a chat." with a link to `/setup`.

## 3. `/quick`: Quick scan

**Purpose.** For someone who is not a developer. Connect a bot, say hello to it, say what it is for and what it must never do, and run a built-in starter pack of tests, in one pass.

**Heading and intro.** "Quick scan". Intro: "A starter pack of tests, run on your bot in one go. It is a first check, not proof that your bot is secure."

The page is one column that grows as steps unlock.

### Step 1: Connect your bot

A group labelled "How is your bot built?" with five choice cards (radio buttons, each with a title and a hint):

| Card | Hint | Fields it shows |
|---|---|---|
| OpenAI-compatible | OpenAI, Groq, Open WebUI, Ollama and similar | API address, Model name, Access key |
| Flowise | A chatflow with a prediction address | Flowise address, Chatflow ID, "Access key (if the chatflow has one)" |
| Paste anything | A link, a key, a code sample or a curl command | A text box (below), then the same detail fields as "Other" |
| Other (custom) | Fill in the details yourself | API address, Message format (dropdown: "Chat completions style" or "Custom body"), then Model name (chat completions style) or Request template and Reply path (custom body), Key header name, Key header prefix, Access key |
| A chat window on my website, coming soon | (none) | Disabled, dashed, dimmed. Not selectable. |

How the fields become a request:
- **OpenAI-compatible:** the address is a base address such as `https://api.groq.com/openai/v1`. Redflag appends `/chat/completions` (once, even if it is already there). Header is `Authorization: Bearer <key>`. For Open WebUI the base is `https://<host>/api`.
- **Flowise:** address plus `/api/v1/prediction/<chatflow id>`, with the message sent as `{"question": ...}` and the reply read from `text`.
- **Other:** exactly what is typed. A custom body must contain `{{prompt}}` where the message goes.

**Paste anything.** A multi-line box labelled "Paste a link, a key, a code sample or a curl command" and a **Read it** button (disabled while the box is empty). It reads the text in the browser (curl, a Windows-copied curl, an OpenAI client snippet, JSON, a bare link or a bare Bearer key). After **Read it**:
- the box is cleared (so a pasted key does not stay on screen);
- the detail fields are filled in below;
- a status line says what was found and what is still needed, without values: "We found: address, key, format. Still needed: reply path."
- If nothing usable is found: "We could not find a bot address in that. Paste a link or a curl command, or fill the details in below."

**Say hello.** A button under the fields, disabled until an address is entered (and, for Flowise, a chatflow ID). It sends "Hello" to the bot through Redflag's backend.

States after Say hello:
- **Failed:** a status line with the plain cause, such as "The server answered with status 401." or "Could not connect to the server." The next step stays closed.
- **Worked:** the bot's answer is quoted ("Your bot answered: “…”"), then the question "Is this your bot's answer?" with two buttons: **Yes, that's my bot's answer** and **No, that's not right**.
- **No:** a status line "Then check the address, the key and the model name, and say hello again." Step 2 stays closed.
- **Yes:** step 2 opens.
- **Changing any field after a Yes** closes step 2 again and asks for a new hello. (The yes belongs to exactly the details that were checked.)

### Step 2: What kind of bot, what for, what it must never do

Shown only after a Yes. Heading "What kind of bot is it?"

- **Kind of bot:** two cards: "A chatbot that answers questions" and "An agent that can also take actions". Nothing is chosen at first.
- **What is it for? (one sentence):** a text field. Example for the helper text: "A customer support assistant for Acme Bank that answers questions about accounts, cards and fees."
- **What must it never do?** A fieldset of tick boxes, all ticked at first, appearing once a kind is chosen. A chatbot gets the default list; an agent gets the same plus extra rules (such as never taking an action the user is not allowed to ask for). The default chatbot list covers: revealing hidden instructions, keys or passwords; revealing one person's private data to another; making things up as fact; unsafe output; going outside its purpose; and wasting its resources. The list comes from the server (`GET /quick-scans/rules`).
  - **Add your own rule:** a field and an **Add rule** button. The new rule joins the same list, ticked, and a starter test is created for it.
- **Sandbox box (agents only):** "This is a test or sandbox environment, not production". An agent can only be scanned if this is ticked.
- **Run starter pack:** the primary button. Disabled until a kind is chosen, a purpose is written, at least one rule is ticked (or added), and (for an agent) the sandbox box is ticked.

What Run starter pack does: one request that checks the connection once more, saves the setup, confirms version 1 and starts the run. The starter pack is a fixed library (no model writes it): attacks for the chosen kind, one test per rule the user added, five normal requests, then rewritten versions (variations) of the attacks. About 30 tests.

Refusals, in the exact words shown:
- Connection failed: "We could not reach your bot: <plain cause>"
- Agent without the box: "An agent can only be scanned in a test or sandbox environment. Tick the box to confirm that this is one."
- No purpose: "Say what your bot is for, in one sentence."
- No rules: "Pick at least one thing it must never do, or add your own."
- Wrong kind: "Choose whether your bot is a chatbot or an agent."
- Another scan running: "A scan is already running. Wait for it to finish, then try again."
- Too many hello checks: "Too many hello checks in a short time. Wait a few minutes and try again."
- Backend asleep or unreachable: "Could not reach the backend. It may still be waking up."

### Step 3: Running and results

The running view, then the finished-scan view (section 2), then the "Tailor these tests" line. Scan time depends on the bot: roughly a few minutes for about 30 tests.

### What the quick scan page must make clear
- It is a first check built from a fixed set of tests, not a full assessment.
- The judge decides every result (there is no plain-rules check and no tool log for a real bot) and has not been checked for accuracy unless labeled.
- Four of the ten OWASP risks (supply chain, data poisoning, excessive agency, vector weaknesses) are not tested for a chatbot, and the report says so rather than showing them green.

## 4. `/mcp`: Check an MCP server

**Purpose.** For someone building an MCP server (a set of tools an AI can call). Redflag looks at the tools the server offers, always checks their descriptions, and, only for tools the owner ticks, calls them with manipulated text and judges what comes back.

**Heading and intro.** "Check an MCP server". Intro: "Tool descriptions are always checked for hidden instructions, invisible characters and open-ended inputs. Tools are only called if you tick them. A clean result is not proof that a server is safe."

### Step 1: Connect

- **Server address:** the server's streamable-HTTP address, usually ending `/mcp`. Must be a public https address; private and internal addresses are refused.
- **Access key:** password field. Optional.
- **How the key is sent** (collapsed section): Key header name (default `Authorization`) and Key header prefix (default `Bearer `). For a server that uses `X-Api-Key`, set the name and clear the prefix.
- **Look at the tools:** button, disabled until an address is entered. Redflag does the MCP handshake and lists the tools. It calls no tool.
- Failure: "We could not reach your bot: <plain cause>" (for example "The server answered with status 401.", "Could not connect to the server.", "That address is not allowed: it points to a private or internal address.").

### Step 2: Choose what to call

After a successful look:
- A heading: "N tools" plus " on <server name>" when the server gave a name.
- A paragraph: "Tick a tool to have Redflag call it with manipulated text. Say whether it only reads or changes things: a tool that changes things is only called on a test or sandbox server."
- A list ("Tools on this server"). Each tool is a card with:
  - a tick box "Call this tool: <name>" (nothing is ticked at first);
  - the tool's description (first 500 characters), or "No description.";
  - a dropdown "What does <name> do?" with **Only reads** or **Changes things**. It starts as "Only reads" only if the server itself says the tool is read-only; every other tool starts as "Changes things".
- **Sandbox box:** "This server is a test or sandbox, not production". Appears only when at least one ticked tool is set to "Changes things".
- **Run checks:** primary button. Always allowed with nothing ticked (description checks only). Disabled when a ticked tool changes things and the sandbox box is not ticked.

Servers can have many tools (the Excel server tested has 46), so the list needs to cope with 50 to 100 entries (the backend caps the list at 100).

Refusals:
- Sandbox missing (also guarded in the page): "A tool that changes things can only be called on a test or sandbox server. Tick the box to confirm that this is one."
- A ticked tool no longer exists: "One of those tools is not on the server any more. Look at the tools again."
- Scan running: "A scan is already running. Wait for it to finish, then try again."

### Step 3: Running and results

Running view (progress shown as "N tests done so far"), then the dashboard. No Run again and no CI panel for MCP scans.

What an MCP scan produces:
- **Description and schema checks (always).** Four checks, each reported once per scan when nothing was found, or once per tool when something was: hidden instructions to the model (critical), invisible or direction-changing characters (high), wording about credential files or sending data out (critical or high), and open-ended parameters (medium or high). Each result names the tool, quotes the short piece of text found, and says how to fix it. The wording always includes that no finding does not mean the tool is safe.
- **Manipulated calls (only for ticked tools).** For a ticked tool's text parameters: a path-traversal string (two variants, only for path-like parameters), injection strings (two), a very large value (20,000 characters) and an instruction hidden in the text. Other required parameters get harmless values. Each result shows: "Called the tool X with {arguments}" (long values cut with their length), what the tool returned (prefixed "(the tool reported an error)" when it said so), and the judge's verdict and reason. A tool with no text parameter shows "not applicable".
- Risks used: LLM01 prompt injection, LLM02 sensitive information, LLM05 improper output handling, LLM06 excessive agency, LLM10 unbounded consumption.
- The dashboard's conclusion for an MCP scan says: "This is a check of an MCP server. The description and schema checks use plain rules that look for known patterns. Redflag only called the tools you ticked, and an AI judge read what each tool sent back."

### What the MCP page must make clear
- Which tools were actually called (the ones ticked) and which were only read.
- That a pass on a manipulated call means the tool handled that one input, not that the tool is secure.
- A server that confines paths or checks inputs will legitimately pass; that is a good result, and the page should not read as if something went wrong.

## 5. The dashboard (shared)

Used in the finished view of both pages (and by `/setup`, `/scan` and the public `/results`).

- **Header:** "Scan #N", the target name, status, start time. Buttons: **Download report** (Markdown) and **Print or save as PDF**.
- **Tabs:** Overview, Tests, Conversations, Compare, History (a real tab strip with arrow keys).
- **Overview:** coloured conclusion banner with counts first ("2 of 26 attack tests failed", attack success rate with its range, normal requests that worked); a donut with a text list beside it; a "since last run" panel after a Run again; the judge note; critical failures; "What this scan checked and did not check" with the ten OWASP risks (Tested or Not tested, counts, MITRE ATLAS tags, and a note that the tags are Redflag's own best match); the settings the scan ran with.
- **Tests:** a filterable table: title, risk, severity, result, AI judge, model.
- **Conversations:** one card per test. At the top, the **Judge accuracy** panel (owner pages). Each card shows status, title, risk, severity, label buttons, and **Show evidence** which expands the message sent and reply (or numbered turns), the tool log or a note that none exists, the judge's verdict and reason, the rule, how to fix it and what answered.
  - **Label mode:** per result with a judge verdict: "Was the judge's verdict (pass) right?" with **Judge was right** / **Judge was wrong**; once set, "You marked the judge right/wrong." and **Clear label**. Results with no judge verdict say "The judge gave no verdict here, so there is nothing to label."
  - **Judge accuracy panel:** with labels, "Agreed with you on X of Y labeled results (Z%)", False alarms (judge failed a reply you say was fine), Misses (judge passed a reply you say broke the rule), a small-sample warning below 20 labels, and a per-risk table. With no labels: "The judge has not been checked for accuracy yet…"
- **Compare:** pick another scan to compare; rule changes between setup versions for real-bot scans.
- **History:** earlier scans of the same target with an Open button.

Colour meaning (light and dark variants exist): green pass, red fail, yellow unclear (inconclusive, error, judge unavailable), grey not applicable / not tested / not run.

## 6. Known issues seen in real use (design should not hide them)

From a real quick scan (#13) and a real MCP scan (#14):

1. **Noisy static results on MCP scans.** The same finding ("the parameter `path` takes any text") is reported once per tool, so a 46-tool server shows 43 identical medium failures and a headline of "46 failed". The real manipulated-call results (26, all passed) are buried. Planned fix: one result per check, listing the tools. Until then the design should expect long lists of near-identical rows.
2. **A vacuous pass.** A manipulated call can be rejected for being malformed (Redflag's harmless filler value did not fit the tool's schema) before the manipulated text was ever looked at, and still shows as a pass. Planned fix: show it as unclear.
3. **Quick scan page wording.** The overview says "If either the plain rules or the AI judge fails a test, the test fails" although no plain rules run on a real bot; the settings line says "up to 150 requests and 0 tokens"; the Run again and CI panels sit above the results and push them down.
4. **Progress for MCP scans** has no total ("N tests done so far").
5. **Judge reasons are written by an AI** and can be long; they are shown in full inside the evidence area.

## 7. Backend calls behind each control (for anyone wiring prototypes)

| Control | Call |
|---|---|
| Unlock (owner-only pages) | `GET /bots` with header `X-Owner-Token` (a 200 means unlocked). Not used by `/quick` and `/mcp` |
| Quick: rule lists | `GET /quick-scans/rules` |
| Quick: Say hello | `POST /quick-scans/check` `{endpoint, key}` |
| Quick: Run starter pack | `POST /quick-scans` `{endpoint, key, bot_type, purpose, must_never[], sandbox_confirmed}` → `{setup_id, version, scan_id, test_count, view_key}` |
| MCP: Look at the tools | `POST /mcp-scans/check` `{url, key, header_name, header_prefix}` → `{server, tools[{name, description, params, effect_hint}]}` |
| MCP: Run checks | `POST /mcp-scans` `{url, key, header_name, header_prefix, exercise[{name, effect}], sandbox_confirmed}` → `{scan_id, view_key}` |
| Progress and results | Owner pages: `GET /scans/{id}`. `/quick` and `/mcp`: `GET /open-scans/{id}?key=<view key>` every 2 seconds until the status is not `running`. No owner header is sent |
| Earlier scans of the target | `GET /scans?bot_id=<slug>` |
| Run again (quick) | `POST /scans/{id}/rerun` `{key}` |
| Label a result | `PUT /scans/{id}/results/{test_id}/label` `{correct: "pass"|"fail"}`; `DELETE` same path to clear |
| Judge accuracy | `GET /judge-accuracy` |

A scan's JSON includes, for each result: `test_id`, `risk`, `kind` (negative attack or positive normal request), `title`, `message`, `reply`, `status`, `evidence`, `rule`, `severity`, `remediation`, `judge_status`, `judge_reason`, and (when labeled) `label`; for conversations, `turns`. MCP scans add `settings.mcp` (target host, server name and version, tool count, which tools were ticked and how they were marked, whether the sandbox was confirmed).
