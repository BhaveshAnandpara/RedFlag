# M4 build plan

Design: `docs/superpowers/specs/2026-10-20-m4-dashboard-design.md`.
Method: test-first, one red-green slice at a time, only at the five seams the owner approved. Commit after each phase with every check green. M1 to M3 behavior and tests keep passing throughout; the M3 page tests are updated where the dashboard replaces the old result view.

Approved seams:
1. **The dashboard**, rendered with the network faked.
2. **The analytics and report functions**: known scans in, numbers, wording and Markdown out.
3. **The scan API over HTTP**, real Postgres: severity and fix notes saved and returned, old results still readable.
4. **The test library file**: every attack test has a severity and a fix note.
5. **The saved sample file**: shape, completed scans, evidence, nothing key-shaped.

No test calls a live model. The live check belongs to the owner in acceptance.

## Phase 1: Severity and fix notes (seams 4 and 3)

1. Library test first: every attack test has a severity of critical, high or medium and a non-empty fix note; normal-request tests have neither; the suite version has moved to 2.
2. The library file gets the first-pass severities and plain fix notes from the design; the model for a test accepts them.
3. API test first: after a scan, every result carries `severity` and `remediation` (null for normal-request tests).
4. Migration adds the two nullable columns; the runner saves them with each result; the store and API return them. Test: a result saved without them (as scan 1 was) still reads, with nulls.
5. The M3 test that expects suite version 1 is updated to 2.

Check: ruff, mypy strict, pytest; migration applies on a fresh database.

## Phase 2: Analytics, comparison and report functions (seam 2)

Pure functions in the frontend, in their own module, shared by the live page, the public page and the report. Slices:

6. Counts by status, and the donut slices (pass, fail, unclear = inconclusive plus error, not applicable).
7. Per-risk stacks: a bar is fully green only with at least one test and every test passed; a risk with no pass or fail is never green; risks with no results are "not tested" and grey.
8. Critical failures: failed tests with critical severity, in order. Old results with no severity are "not rated" and never counted as critical.
9. Attack success rate: attack tests that failed out of those that ended pass or fail, with a 95% Wilson interval; errors, inconclusive and not-applicable shown beside it and left out of the denominator; normal requests excluded and reported as "worked: x of y".
10. Small-sample note when fewer than 20 attack tests ended pass or fail; the rate is only ever given beside its counts.
11. The conclusion text: counts first, critical count, how many tests could not be completed, how many risks were not tested, and the not-a-security-claim line. A test asserts it never contains "safe", "secure" or "ready".
12. Compare: same model only when both scans' model sets are identical; otherwise it names the models and warns; tests that changed status; tests in only one scan; suite versions that differ.
13. The Markdown report: conclusion, settings, every test, failures with severity, evidence and fix, inconclusive and errored tests, not-tested risks, and the closing line. A test asserts a scan with untested and inconclusive parts says so in the report.

Check: lint, typecheck, test.

## Phase 3: The dashboard (seam 1)

Colour tokens for pass, fail, unclear and grey in light and dark mode, and a status badge that always shows the word. Slices, each a rendered-page test first:

14. Overview: the conclusion, the donut with a text equivalent, the per-risk bars with their text, the critical failures, normal requests, and the attack success rate with counts and range.
15. Untested and not-applicable risks are grey and worded as not tested; nothing reads as an all-clear.
16. Tabs: Overview, Tests, Conversations, Compare and History, reachable by keyboard.
17. Tests tab: a table with status, test, risk, severity and the model; filter by status, risk and severity; sort.
18. Conversations tab: message, reply, tool log with arguments, evidence, rule, fix note and model for each test.
19. Compare tab: two scans side by side with the same-model or different-model line and the changed tests.
20. History tab: earlier scans with counts; choosing one opens it.
21. Download report button produces the Markdown.
22. Read-only mode: no run button and no network request, used by the public page.

Check: lint, typecheck, test, build, bundle check.

## Phase 4: The owner page (seam 1)

23. `/scan` shows the dashboard on a finished scan, replacing the old result view; the M3 page tests that covered the old view move to the dashboard.
24. Live progress: tests done, and after 30 seconds without a new result the note about a possible free-tier wait.
25. Compare and History use the existing API with the password header; the password stays in memory only.

## Phase 5: The public page and saved samples (seam 5)

26. Shape test first on the sample file with a fixture: it holds one completed weak scan and one completed hardened scan, each result has evidence and a recorded model, and nothing is shaped like a key, token or connection string (the same patterns as the M2 recordings test; random `CANARY-` values are allowed).
27. The export script reads two chosen completed scans from the live API with the owner password from the git-ignored `.env.local`, refuses a scan that is not completed or a file with key-shaped text, and writes the sample file. It prints only scan numbers and models.
28. Route `/results`: the dashboard, read-only, with Compare preselected as weak versus hardened and "saved on [date], with [model]" on each scan. Until the real samples exist, an honest "No saved scans yet" state.
29. Links to it from the home page and from the explainer page.

Check: lint, typecheck, test, build, bundle check.

## Phase 6: Docs and CI

30. `docs/M4-setup.md` in the same shape as M3: purpose, how it works with a diagram, the colours and words, the conclusion rules, how to export samples, testing, problems met, acceptance steps, limits, what M4 achieved. README roadmap and tests table updated.
31. CI runs the new tests; the secret scanner stays on.

## Phase 7: Deploy (owner clicks, builder guides)

32. Push, confirm CI is green, confirm the backend deploy runs the new migration and the frontend deploy shows `/results`.

## Phase 8: Live acceptance (owner)

Run a clean live scan of the weak bot and one of the hardened bot (or ask me to). Pick or let me pick the completed pair, run the export, commit the sample file, and check: the owner dashboard with its tabs, the public `/results` page without a password, the Compare line about the model, the report download, grey for untested, and that a visitor cannot start a scan. Only after the owner approves does M5 start.

## Risks to watch

- Charts that look right but say too little to a screen reader or colour-blind reader. Slices 14 and 15 test the words and text equivalents.
- A conclusion drifting toward "safe". Slice 11 asserts the banned words.
- A sample scan comparison where different models answered. Slice 12 covers the wording.
- Free-tier quota ending a live scan early. The honest errors still show, and the owner can rerun later.
- The M3 page tests needing a larger rewrite than expected. Slice 23 plans for it.
- A key-shaped string slipping into a saved sample. Slices 26 and 27 guard both the file and the script.
