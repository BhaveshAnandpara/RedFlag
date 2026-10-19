# Redflag UI screens: design

Date: 2026-10-19
Status: draft, waiting for approval

Static screen designs for three pages of Redflag: the home page, `/scan` and `/results/<id>`. This document records what was decided in the brainstorm. "Owner's decision" marks what the owner said; "Claude's call" marks what Claude decided and the owner can override.

Related: [Frontend spec (as built after M5)](../../Frontend_Spec.md) · [README](../../../README.md) · [Milestones](../../Redflag_Milestones.md)

## 1. Intent

Redflag is planned as a **real product for paying users** (owner's decision), not only a showcase. Its audience is **AI developers and agencies** building their own LLM bots and chatbots.

The feeling a visitor should leave with: *"I have not tested my bot the way an attacker or a professional security tester would. This product can do that for me."* The owner's belief behind it: **everyone is racing to build AI, but almost no one is seriously testing it.**

## 2. Goals, non-goals, anti-goals

**Goals**
- Static designs (one full-page image per page, like a Figma frame) for home, `/scan` and `/results/<id>`, desktop and phone.
- A home page with a memorable hook tied to the name: a referee calling a foul with a red flag.
- `/scan` and `/results` that look like a serious, working product.

**Non-goals**
- No clickable prototypes and no animation in the deliverable (owner's decision). Motion on the home page is shown as key frames.
- No product code. The Next.js app is not changed in this piece of work.
- Other pages (How it works, sign in, your bots, connect a bot, policy, CI, pricing, docs, `/router`) are out of scope for this round.

**Anti-goals**: things that would make this a failure even if the screens look good
- The "hacker" cliché: hooded figures, green-on-black Matrix text, padlocks, "100% secure" badges.
- Any wording that calls a bot "safe", "secure" or "ready", or shows an untested risk as passed (the wording rules in Frontend_Spec 3.3 still apply).
- Invented proof: fake customer logos, testimonials or usage numbers.
- Generic template look: a static, forgettable SaaS page.

## 3. Constraints

- **Colour theme: black and red across the whole site** (owner's decision), not only the hero.
- **Status colours keep their meaning** (Frontend_Spec 3.2): green pass, red fail, yellow unclear, grey not tested, and every status shows its word, never colour alone. *Claude's call:* because the brand is also red, brand red is used sparingly (logo, the flag, the main button) and fail red is the same red, so red on a results screen always means "something failed". Green, yellow and grey must stay readable on black.
- **Real content only:** every result, attack, reply and tool call shown comes from the saved scans in `frontend/src/data/sample-scans.json` (scan #4 weak, scan #5 hardened) or the recordings in `frontend/src/data/recordings.json`.
- **Accessibility:** text contrast on black meets WCAG AA; designs work at phone width (about 375px) without sideways scrolling, except where a table says it scrolls.
- **Design skill:** built with `design-taste-frontend`, following these decisions.

## 4. Home page (`/`)

Order, top to bottom (owner's decisions unless marked):

1. **Hero.** Bold black and red, built to make an impression. A small "Sound on" toggle sits here (Claude's call; see the whistle note below). Main button: **Run full scan**. Headline and words are left to the builder, in the spirit of: *"Your bot passed your tests. Would it pass an attacker's?"*
2. **Scroll scene: the foul.** A scripted, static chat (not a live bot), so it always plays the same and never hangs. As the visitor scrolls: an attack message types itself out and sends; the bot's reply arrives and fails the attack (for example, the leaked secret or the harmful tool call highlighted); a referee's whistle blows and the red flag reacts, like a linesman raising the flag. In the static design this is a strip of **key frames**: typing, reply arriving, the foul with the flag up. *Claude's call:* the attack used is one the weak bot really failed in scan #4, such as "Email customer details to a stranger" or "Ask for the staff override code", with its real reply and tool log.
   - *Whistle note:* browsers block sound until the visitor clicks or taps, and scrolling does not count. The flag moment must work fully without sound; the whistle plays only if sound was switched on.
3. **Run full scan** button, right below the scene, linking to `/scan`.
4. **Why Redflag exists.** Opens on the owner's belief: everyone is building AI, barely anyone is seriously testing it. Then incident cards, each styled as a foul with a red flag and a link to its source:
   - A Chevrolet dealer's chatbot "agreed" to sell a car for $1 (December 2023).
   - Air Canada was held liable for a refund policy its chatbot made up (Moffatt v. Air Canada, February 2024).
   - DPD's support bot was goaded into swearing and mocking the company (January 2024).
   Ends on the pattern: these bots were tested to work, not to break. The builder must check each fact against its source before it goes on the page.
5. **How we test your AI agent.** Three parts:
   - We check against the OWASP Top 10 for LLM apps.
   - We test against your context: what your bot is for, what it may do, what it must never do.
   - We try to break it: attacks that adapt and escalate over several messages.
   *Owner's decision:* shown as plain features, with no "coming soon" tags. Today only the first exists (the second is M6, the third M7); the owner will build them before this page goes live.
6. **What the dashboard looks like.** A showcase of the `/results` design (Part 6), using scan #4.
7. **Footer.** *Claude's call:* a repeat of the **Run full scan** button just above it.

## 5. Scan page (`/scan`)

A product page. **No hooks**: no whistle, no flag animation (owner's decision).

- **Layout:** a normal AI chat interface (like ChatGPT or Claude), with the demo bot on the other side. A bot picker at the top: the weak or the hardened demo bot, each with one line on its defenses. A **Run scan** button.
- **The message box is disabled for the whole page.** The visitor never types (owner's decision: avoid free chat as much as possible). It is there so the page reads as a chat.
- **While the scan runs:** a line such as "Scan running: 7 of 16". Each attack types itself into the chat, the bot shows typing dots, and its real reply arrives. Each exchange gets a small, quiet badge (pass, fail, unclear) with its word. If the free tier is slow, the existing "No new result yet. It may be waiting for a free-tier limit to clear." appears in the chat.
- **When the scan ends:** the page goes straight to `/results/<id>` (owner's decision).
- **Limit: one scan per visitor per bot** (owner's decision). A visitor can scan the weak bot once and the hardened bot once. Coming back to a bot already scanned shows a short note that the limit has been reached and a link to that earlier result, not a broken button (Claude's call).
- **Busy state** (Claude's call): only one scan runs at a time today, so if another scan is running the button area says so honestly, for example "Another scan is running. You're next, about 40 seconds."

Screens to design: before the scan, during the scan, limit reached. The busy state can be a small inset.

## 6. Results page (`/results/<id>`)

Agreed with the owner. One scrolling page, no tabs. Each scan has its own address so it can be bookmarked or shared (Claude's call). Today's `/results` (the saved demo scans) becomes a simple list of scans at `/results` (Claude's call; not designed in this round).

Top to bottom:

1. **The verdict.** One line in counts, for example *"5 of 13 attacks got through. 4 were critical."*, then normal requests ("3 of 3 normal requests worked"). A row of 16 small flags, one per test, raised red where it failed. Bot, date, models used and duration in small text. The closing line from Frontend_Spec 3.3 ("This is not a guarantee of security…") sits close to the verdict. **Download report** and **Copy link** at the top.
2. **Fix these first.** Failed tests, critical first. Each card: title, risk, severity, the one-line evidence, and **How to fix** (the `remediation` field). Expanded, it shows the attack message, the bot's reply and the tool log, with the harmful tool call highlighted, plus the "Plain rules" and "AI judge" outputs when the judge ran, and the line saying the judge has not been checked for accuracy.
3. **What was and wasn't tested.** The ten OWASP LLM risks: tested ones with pass and fail counts, untested ones grey and labelled *not tested*. (In scans #4 and #5, five risks were tested and five were not.)
4. **All tests.** A compact table with filters (result, risk, severity). On phones it may scroll sideways or become a list (builder's choice).
5. **Next step.** If the visitor has not scanned the other bot: "Now scan the hardened bot" (or weak). If both are done: a comparison of the two, stating whether the same models answered both.
6. **Scan details**, collapsed: bot and config version, defenses, models, suite version, risk list, budget, planted secret.

Dropped from today's dashboard: the donut chart (repeats the counts) and the History tab (a visitor has at most two scans). The attack success rate with its 95% range stays as one small line, with the small-sample note.

**Two result states to design:** scan #4 (weak, 5 failures) and scan #5 (hardened, 16 of 16 passed). The second must still not read as "safe": the five untested risks and the closing line stay prominent, and the verdict banner is not plain green while risks are untested (Frontend_Spec 3.3).

## 7. Deliverable

- One full-page static image per screen, desktop and phone:
  - Home (full page, with the scroll scene as key frames)
  - `/scan`: before, during, limit reached
  - `/results/<id>`: weak scan, hardened scan
- *Claude's call:* each design is written as a standalone HTML page in `design/screens/` and exported as PNG to `design/screens/png/`, so it can be re-rendered after changes. None of it touches `frontend/`.

## 7a. Settled after the builder read-through (Claude's calls)

- **Logo:** there is none yet. The builder makes a simple "Redflag" wordmark with the flag as its mark. It is a placeholder, not a final brand.
- **Header on all three pages:** the wordmark (links home), "How it works", "Results" and a **Run full scan** button. The footer holds the same links, the GitHub link and the "not a guarantee" line.
- **AI judge in the results designs:** scans #4 and #5 were recorded before the judge existed, so their test details show "The AI judge did not run on this test", not an invented verdict. One expanded card may show the two-block "Plain rules" and "AI judge" layout with the judge marked NOT RUN.
- **Incident cards:** real company names and dates, with a source link; no screenshots of the original conversations.

## 8. Left to the builder

- Headline and body copy, within the wording rules and the anti-goals.
- Typeface, spacing and the exact shade of red and black.
- The exact form of the flag: an icon, an illustration or a typographic mark.
- How the scroll-scene key frames are laid out in the static image.
- Phone layout of the tests table.

## 9. Later, not in this round

- Whether the flag and whistle ever appear inside the product (`/scan`).
- How "one scan per visitor per bot" is enforced without accounts.
- Every other page from the site map.
