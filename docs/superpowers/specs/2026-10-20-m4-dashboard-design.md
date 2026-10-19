# M4: Dashboard and reports: design

Status: draft for approval. Date: 2026-10-20.
Builds on: [M3 setup](../../M3-setup.md), [M2 setup](../../M2-setup.md). Milestone definition: [Redflag_Milestones.md](../../Redflag_Milestones.md), section M4.

## Intent and why

M3 gave Redflag a scan engine and a plain list of results. M4 makes those results understandable to someone who has never seen the product: a dashboard with charts, a conclusion that never overclaims, a table of every test, the full conversations, a comparison of two scans, a history, and a downloadable report.

The owner's vision (in their words, lightly tidied): when a scan runs it should show analytics such as a pie diagram and other diagrams, the critical tests that failed, and a conclusion, including whether the same AI model answered when two scans are compared. Everything is colour-coded red, yellow and green, and organised in tabs: a results tab with analytics, a detail table, conversation details and a history tab.

The dashboard serves two audiences with one design: the owner, who can run live scans, and a first-time visitor, who sees **saved real scans** of the weak and the hardened bot in the same dashboard, with no way to start a scan (live scans burn the bots' small free quota).

Spec items: FR-22, FR-24, FR-31, FR-32, FR-33, FR-34, FR-35, FR-36, FR-37, FR-38.

## Goals

- A **dashboard with tabs**: Overview, Tests (a table), Conversations, Compare and History, plus a **Download report** button.
- **Overview** with: a conclusion line, a donut chart of the results, a bar per OWASP risk, a list of critical failures, how many normal requests worked, and the attack success rate with its sample size and an uncertainty range.
- **Colour coding** that carries meaning and is never the only signal: green for pass, red for fail, yellow for unclear (inconclusive or error), grey for not tested or not applicable. Every status keeps its word beside the colour.
- A **severity** (critical, high, medium) on every attack test and a short **how to fix this** note, both kept in the test library and saved with each result.
- A **Compare** tab: pick two scans and see counts side by side, which tests changed, and a plain statement of whether the **same AI model answered both**.
- A **History** tab listing earlier scans.
- A **Markdown report** that clearly separates what was tested, what was not, and what was inconclusive or errored.
- The owner's `/scan` page gets the dashboard and the existing single **Run scan** button with a live progress view.
- A **public results page** showing saved real scans of the weak and the hardened bot in the full dashboard, read-only, labelled with when and with which model they were recorded.

## Non-goals

- No scan configuration screen: the single **Run scan** button, which runs everything, stays.
- No visitor-started scans, no accounts, no scheduling (M9), no judge model (M5), no policy builder (M6), no adaptive attacks (M7), no external targets (M8).
- No trend charts across many scans (History is a list), no PDF export, no email.
- No new test content beyond severity and fix notes on the existing 16 tests.
- No change to how verdicts are decided.

## Anti-goals (a failure even if it technically works)

- **Anything shown as green that was not actually tested**, or a green summary that reads as "all clear". Untested and not-applicable risks are grey.
- A conclusion that says or implies the bot is secure, safe or ready to release.
- Colour as the only signal of a status.
- A percentage without the counts and sample size behind it, or a rate presented as precise when it rests on a dozen tests.
- A comparison that credits the defenses for a difference without saying whether a different model answered each scan.
- A report that hides the untested, inconclusive or errored parts, or that shows only failures.
- The public page looking live. It must say it is saved, with the date and model.
- Any way for a visitor to start a scan, spend quota or reach the owner-only API.
- A key, token or connection string in a saved sample, a report or the browser bundle.

## Decided by the owner

- The dashboard has tabs for results with analytics, a detail table, conversation details, history and comparison, with charts and red / yellow / green colour coding.
- The conclusion covers whether the same AI model answered when scans are compared.
- **Option C**: a public page of saved sample scans, plus the owner's live scan on the same dashboard. Visitors cannot run scans.
- **No scan configuration step**: keep the single **Run scan** button that runs everything.
- Severity per test, with the owner able to edit it; the conclusion never says "safe".
- Confirmed layout: Overview, Tests table, Conversations, Compare, History, Download report, and a read-only public sample page.

## Constraints

- Free tiers: Vercel Hobby for the page, no new paid service. The public page makes no network call and costs no AI quota.
- The owner-only API and its password lock are unchanged. The public page only reads files built into the site.
- No heavy new dependencies. The frontend keeps lint, typecheck, Vitest, build and the bundle check, and the secret scanner stays on.
- Accessibility: every chart has a text equivalent (a table or list), colours meet contrast in light and dark, and the dashboard works at phone width and by keyboard.
- Existing M1 to M3 behavior and tests keep working. Scans from before M4 (such as scan 1) must still open, with severity shown as "not rated".

## Design

### The parts

1. **Severity and fix notes in the test library.** Each attack test gets `severity` (critical, high or medium) and `remediation` (a short plain "how to fix this" note). The suite version goes up. The scan runner saves both with each result when the scan runs, so a result stays a faithful record even if the library changes later. Normal-request tests carry no severity. Older results without them are shown as "not rated".
2. **Analytics functions** (pure, in the frontend, shared by the live page, the sample page and the report): counts by status, the donut slices (pass, fail, unclear, not applicable), per-risk summary, critical failures, normal-request result, attack success rate as "failed of tested" with a 95% uncertainty range, and the conclusion text. A small-sample note appears when the number of attack tests is low.
3. **The conclusion**, built from the numbers and always with the same shape: how many attack tests failed and how many were critical, how many tests could not be completed, how many risks were not tested, and that this is not a claim of security. It never uses "safe", "secure" or "ready". A scan with errors says how many tests could not be completed.
4. **The dashboard component**: takes one scan (the API's response) and renders the tabs. It is the same component for the owner and the public page.
   - *Overview*: conclusion, donut with a text equivalent, per-risk bars, critical failures, normal requests, attack success rate, the tested / not tested list, and the settings the scan ran with.
   - *Tests*: a table with status, test, risk, severity and the model that answered, filterable by status, risk and severity, sortable.
   - *Conversations*: each test's message, reply, tool-call log with arguments, evidence, rule and fix note.
   - *Compare*: two scans side by side (counts, which tests changed status), and a line that says whether the same model or models answered both, and that a different model means the difference may not come from the defenses. Also whether both scans ran the same tests (suite version).
   - *History*: earlier scans with counts, opening one loads it into the dashboard (owner page). The public page lists the saved samples.
5. **The owner page** (`/scan`): unlock, pick a bot, **Run scan**, live progress (tests done, the one running), and when it finishes the dashboard opens on the result. The Compare and History tabs use the existing API (`GET /scans`, `GET /scans/{id}`); no new endpoint is needed for the dashboard itself.
6. **Saved sample scans and the public page**: a script run by the owner reads two chosen completed scans (one weak, one hardened) from the live API with the owner password and writes them to a file in the frontend source tree. The public page (`/results`) bundles that file, makes no network call, shows the dashboard read-only with Compare preselected as weak versus hardened, and labels each scan "saved on [date], with [model]". The home page and the explainer page link to it. The script refuses scans that are not completed and refuses a file holding anything shaped like a key.
7. **The report**: a function that turns a scan into Markdown, available from a **Download report** button on both pages. It has sections for the conclusion, the settings, what was tested with each result, what failed (with severity, evidence and fix), what was inconclusive or errored, and what was not tested, and it ends with the not-a-security-claim line.

### Colour and words

| Status | Colour | Word |
|---|---|---|
| pass | green | PASS |
| fail | red | FAIL |
| inconclusive, error | yellow | INCONCLUSIVE, ERROR (grouped as "unclear" in the chart) |
| not applicable, not tested | grey | NOT APPLICABLE, NOT TESTED |

Colours are design tokens that adapt to light and dark mode.

### Flow

```
owner: Run scan -> progress -> dashboard opens on the finished scan
owner: Compare / History use earlier scans from the API
owner (once): export script saves a weak scan and a hardened scan into the site
visitor: /results -> the same dashboard, read-only, on the saved scans (no network call)
anyone with a scan on screen: Download report -> Markdown
```

## Testing

Tests only at seams the owner agrees to before any test is written (the `tdd` rule). Proposed seams, each with what it catches and misses:

1. **The dashboard, rendered with the network faked.** Feed it scans and check: the conclusion wording (never "safe"), the donut's text equivalent, grey for untested risks, critical failures listed, the tabs, the table's filters, conversations, Compare (same model and different model wording, and which tests changed), History, and the public page being read-only with no run button and no network call. Catches rendering, wording and honesty mistakes. Misses how it looks at real sizes.
2. **The analytics and report functions.** Known scans in, numbers, conclusion text and Markdown out, including the uncertainty range, the small-sample note, and a report that separates tested, untested and inconclusive. Catches wrong maths and a report that hides the untested parts.
3. **The scan API over HTTP with real Postgres.** Severity and fix notes are saved with each result and returned; a result saved before M4 (no severity) still reads fine. Catches a bad migration or lost fields.
4. **The test library file.** Every attack test has a severity and a fix note, normal-request tests have none, and the suite version moved. Catches a missing rating.
5. **The saved sample file.** It parses, holds one completed weak scan and one completed hardened scan, every result has its evidence, the models are recorded, and nothing is shaped like a key, token or connection string. Catches a hand-edited or unsafe file.

Prior art: M3's scan API and page tests, and M2's page and recordings-file tests. No CI test calls a live model.

## Done when

- A first-time visitor can open the public results page and read the saved weak-versus-hardened scans without any documentation.
- The Compare tab shows the effect of the hardened configuration and says whether the same AI model answered both scans.
- The Overview shows the conclusion, the donut, the per-risk bars, the critical failures, the normal-request result and the attack success rate with its counts and uncertainty.
- Untested and not-applicable risks are grey and listed as not tested, and nothing says the bot is secure.
- The report downloads on both pages and clearly separates tested, untested and inconclusive risks.
- The owner's `/scan` page runs a live scan with progress and opens the dashboard on the result; a visitor cannot start a scan.
- Statuses carry words as well as colours, and the pages work at phone width and by keyboard.
- Old scans still open. CI, including the secret scanner and the production-image check, is green.
- `docs/M4-setup.md` and the README are updated.

## Owner actions during the build

- Approve the written design and the five proposed test seams before building starts.
- After the deploy, run a clean live scan of each bot, so there is a fair weak-versus-hardened pair (or ask me to). The bots' free quota is used each time.
- Say which two scans to save as the public samples, or let me pick the latest completed pair.
- Check the owner dashboard and the public page on the live site.

## Calls made without the owner (change any of these)

- Charts are drawn by hand as SVG with a text equivalent beside each, with no chart library.
- The uncertainty on the attack success rate is a 95% Wilson interval, shown as a range, with a note when the sample is small.
- I choose the severities and write the fix notes, and the owner edits them in the test file. First pass: leaking another customer's data, leaking the secret, and the two poisoned-article tests that email or refund are critical; an unauthorised refund or email is critical; the other injection and refund-limit tests are high; the unsafe-output tests are high for the off-site image and medium for the script tag; prompt leakage is medium.
- Severity and the fix note are saved with each result at scan time, as nullable columns, so old results simply have none.
- The report is built in the browser from the scan data, so the public page can offer it with no backend.
- Compare and History run in the browser from the existing API; no new endpoint is added for the dashboard.
- The public page is `/results` and the owner's page stays `/scan`.
- The chart's "unclear" slice joins inconclusive and error; the table keeps them separate.
- The export script reads from the live API with the owner password in the git-ignored `.env.local`, and the sample file is committed.
- Visitors see two samples (weak and hardened). More samples can be added later by running the script again.

## Details settled after the builder check (all my calls)

- **"Same model" in Compare.** M3 already saves the model and provider on every result and a `models_used` list on every scan. Compare says "the same model answered both" only when both scans' sets of models are identical. If the sets differ (including when a rate-limit fallback mixed models inside one scan), it says which models answered each, and that the difference may not come from the defenses. It also notes when the suite versions differ.
- **What the API already returns.** `GET /scans` returns each scan with counts per status. `GET /scans/{id}` returns the settings, every result (message, reply, tool log, evidence, rule, risk, model, provider) and a summary that already lists all ten catalog risks as tested, attempted with no result, or not tested. The dashboard needs only the severity and fix-note fields added; nothing else about the API changes.
- **Live progress.** The page polls `GET /scans/{id}` as M3's does. If no new result has arrived for 30 seconds, it adds "No new result yet. It may be waiting for a free-tier limit to clear" so a rate-limit pause does not look like a hang.
- **Attack success rate.** It is attack (negative) tests that failed, out of attack tests that ended pass or fail. Inconclusive, error and not-applicable tests are left out of the denominator and shown beside it ("2 could not be completed"). Normal-request tests are never part of it; they get their own "worked: x of y" line.
- **Which risks are "not tested".** A risk with no results is "not tested"; a risk whose results are all error, inconclusive or not applicable is "attempted, no result". Both are grey, labelled with words. This is the summary M3 already produces.
- **Colouring a risk bar.** A bar is stacked by status, so a risk with one pass and one error shows a green part and a yellow part. A bar is fully green only if it has at least one test and every test passed. A risk with no pass or fail never shows green.
- **The rate in the conclusion.** The conclusion always states counts first ("4 of 13 attack tests failed"). The percentage and its range appear only beside the counts, with a small-sample note when fewer than 20 attack tests ended pass or fail.
- **The saved samples.** Tests use a fixture scan, not a real one. Until the owner has run two clean live scans, the public page shows an honest empty state ("No saved scans yet") instead of fake data. Once the export script has run, the real file is committed. "Shaped like a key" reuses the patterns M2's recordings-file test already checks (Groq, Google and OpenRouter key shapes, bearer tokens, connection strings). The fake canary secrets are random `CANARY-` values that are not key-shaped and are allowed in the file, because a leak test's evidence legitimately shows them.
- **The site.** It is a Next.js app with the App Router, so `/scan` and `/results` are routes in the existing structure. The bundle check only looks for connection strings; there is no size limit to trip, and the sample file is small.
- **Editing severity.** File-only: the owner edits the test library, there is no in-app editor.
- **Comparing scans from different suite versions.** Tests that appear in only one scan are listed as "only in scan A" or "only in scan B", and the page says the suite versions differ.

## Left to the builder

- Layout, component split, exact chart geometry, and spacing, within the site's existing look.
- Wording of the fix notes (each is short and plain), and the exact threshold for the small-sample note.
- How filters and sorting are laid out, and how Compare lists changed tests.
- The export script's command-line shape.
