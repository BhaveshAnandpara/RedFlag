# HTTP bots only: Staging and Production modes

Date: 2026-10-27. Status: draft, waiting for approval.

## Intent

Redflag tests AI, not tools. So Test your bot is for HTTP bots only. MCP servers are switched off.
The user says whether the bot is in **Staging** (in development, not published) or **Production**
(live). Staging gets the full testing architecture agreed on 2026-10-26. Production gets a lighter,
OWASP-style set that the user picks from.

## Goals

- A simple Staging / Production toggle at the top of step 1 of `/quick`.
- Staging: a user tick saying "this is a dev or test copy, not published", then the full
  architecture (Recon, interview, personas, test spec, validator, review, runner, evidence and
  judge, report), for HTTP bots.
- Staging: logs in the bot's replies make testing better but are never required.
- Production: Redflag generates OWASP-top-10-style tests, shows them, and the user chooses which to
  run. No logs needed.
- MCP stays in the code but is not reachable.

## Non-goals and anti-goals

- No MCP in the product for now. The MCP code is not deleted.
- Redflag does not try to detect whether a bot is really a sandbox. It is the user's word.
- The user is never asked to describe their log format.
- A bot with no logs is never blocked from a Staging scan, and is never presented as having been
  tested as well as one with logs.

## What was decided (the user's words)

1. **MCP:** "for now just comment it or disable it." Already off behind `MCP_ENABLED = false`
   in `frontend/src/components/connect-ways.tsx`; the nav link and `/mcp` page are removed.
2. **Staging means** the bot is in dev or not published. A check confirms it is a sandbox, and that
   check is **user discretion**: the user ticks it.
3. **Staging scan:** the user just says "test the bot" and Redflag runs the whole architecture.
4. **Logs:** if the replies have no logs, say so plainly: "We don't see logs in your bot's
   response. We can test your bot a lot better if it returns logs with each response, but it isn't
   mandatory." Verified when saying hello.
5. **Reading the logs:** Redflag gives the bot's hello reply to the **supervisor LLM**. It works
   out whether the reply holds logs and what their structure is. The user is not asked.
6. **Production:** Redflag generates OWASP-10 tests and the user selects which to run. That
   selection is the user's discretion.
7. **Tickets:** the discussed architecture stays; it applies to HTTP bots only, not MCP.

## My calls (not agreed yet)

- **One tick.** The Staging tick replaces today's "this is a test copy" box for agents. Production
  has no tick.
- **Production changes no data.** The production tests are written to not change data. A test that
  could is marked so the user sees it before choosing. The user still has the final say.
- **Log detection fences the reply as data.** The bot's hello reply is untrusted text. It goes to
  the LLM fenced as data, like the other prompts, and the LLM only returns a structured answer:
  logs found yes or no, and the fields it saw.
- **Production uses the existing starter pack as a base.** `quick/` already generates a pack of
  tests; production adds the selection step and OWASP labels.
- **Ticket changes for HTTP-only:**
  - 4 is done and MCP is off. 5 is parked.
  - 6 Recon shrinks to hello, the bot describing itself, and log detection.
  - 7 to 9 and 12 to 16 apply as written. Check 4 of the validator (tools exist) drops.
  - 10 and 11: Mode A (direct tool call) drops. Without logs, the oracle works from the reply
    and planted traps.
  - 13 and 14: only Mode B (conversation). Mode C only for bots that read documents.
  - 15: the judge matters more; most results without logs read "based on the reply only".

## What is left to the builder

- The exact wording and layout of the toggle and the log note.
- The shape of the LLM's log-detection answer and how it is stored for later tickets.
- How the Staging and Production flows share step 1 and diverge after it.
- Tests for each of the above.
