# M6 build plan

Design: `docs/superpowers/specs/2026-10-20-m6-your-own-bot-design.md`.
Method: test-first, one red-green slice at a time, only at the five seams the owner approved. Commit after each phase with every check green. M1 to M5 behavior and tests keep passing throughout. The only faked parts are the outside models and the user's endpoint (a stand-in HTTP server in the tests).

Approved seams:
1. **The setup conversation over HTTP**, scripted fake model, real Postgres.
2. **The generator and supervisor on their own interface**, fake model.
3. **The HTTP target adapter** against a stand-in server.
4. **The scan API over HTTP**, real Postgres, stand-in endpoint, fake judge.
5. **The pages and the dashboard changes**, network faked.

No test calls a live model or a real outside server. The live check belongs to the owner in acceptance. Nothing starts building until the owner approves this plan.

## Phase 1: The HTTP target adapter and address checks (seam 3)

A new backend package `targets/` that does not import the sandbox. Slices, each a test first:

1. OpenAI-compatible format: the adapter posts a chat-style body with the prompt and returns the text at `choices.0.message.content`.
2. The key is sent only in the configured header (default `Authorization: Bearer ...`), never in the body or the URL, and never appears in an error message or the returned notes.
3. Custom format: a JSON template with `{{prompt}}`, the prompt escaped into JSON (quotes, newlines and braces in the prompt cannot break the template), and a dotted reply path with array positions.
4. A reply that is not JSON, a missing path, a streamed (event-stream) reply, an empty reply and a reply over the size cap each give a clear error result, never a pass.
5. Timeouts, connection failures and non-success statuses give errors with the cause (status code or kind), never raise out of the adapter.
6. Redirects are not followed and are reported as an error.
7. Address refusal: loopback, private, link-local, the cloud metadata address, unspecified and IPv6 equivalents are refused; a hostname that resolves to one is refused; a literal IP in the URL is checked; a public address is allowed; both https and http and any port are allowed; Redflag's own backend address is refused.
8. The connection is made to the resolved address (so a changed DNS answer cannot sneak past), with the original host name for the request and certificate check.
9. If the reply contains the key, it is replaced by a marker before the reply is returned.
10. Test connection: one harmless message, returns the status, the raw reply (trimmed) and what the parsed reply would be; limited to 5 attempts per setup.

Check: ruff, mypy strict, pytest.

## Phase 2: Setup data and versions (seam 1, storage)

Slices, API tests first with real Postgres:

11. Creating a draft setup returns an id; the draft holds fields, chat history and contexts, and survives a read after a restart of the app object (a page refresh).
12. Fields have a source (user, model, edited by you) and a status (stated, inferred, unclear); a field edited by the user is locked and a model update to it is ignored; unlocking lets the model change it again.
13. Confirming the rules saves an immutable numbered **setup version** (fields and both contexts); editing afterwards starts a new draft that becomes version N+1 when confirmed; an old version never changes.
14. The required-field check: a working connection test, a non-empty purpose, and at least one forbidden-type rule whose status is stated or confirmed; a rule the model only inferred does not count until the user confirms it.
15. The endpoint key is never in any saved row, draft, version, log line or response (searched for in every table after a full session).
16. Migration for setup drafts, setup versions, generated tests and a link from scans to a setup version; scans from before M6 still read.

Check: ruff, mypy strict, pytest; the migration applies on a fresh database.

## Phase 3: Interviewer and supervisor (seams 1 and 2)

17. The interviewer, given a user message, returns an updated set of fields and the next question; required items are asked before optional ones; the user's text arrives as quoted data.
18. The follow-up cap: after about 8 follow-up questions it stops asking; every question can be skipped and a skipped item is marked unclear.
19. The chat session cap (about 30 messages) ends with a plain message, not an error.
20. The key never appears in any prompt sent to the interviewer or supervisor (checked on the captured prompts).
21. The supervisor, given the fields, examples and file contents, writes a tester context and a judge context with every item tagged with its source; the user's examples go to the judge context verbatim and fenced as data; the judge context is capped at about 6,000 characters and anything cut is noted.
22. Uploaded files: only text, markdown and JSON, a size cap and a count cap; anything else or too large is refused with a plain message; contents are treated as untrusted data and not saved with the version.
23. A malformed interviewer or supervisor answer is retried once, then reported as a clear failure; a quota failure gives a clear error and no fallback to another kind of model.
24. "Regenerate contexts" rebuilds them but keeps context fields the user edited.

Check: ruff, mypy strict, pytest.

## Phase 4: The test generator (seam 2)

25. From a confirmed setup version, the generator returns at most 30 tests; each has id, title, risk (from the OWASP catalog, or none for a normal request), kind, severity, the exact prompt, what we are trying to find out, what a correct reply looks like, the rule it rests on, an unclear-rule flag and a real-action flag.
26. Validation: more than 30, a risk not in the catalog, a missing field, an empty prompt or two identical prompts makes the output malformed; it is retried once, then reported as a failure to generate.
27. An app with no tools gets no tool-misuse tests; a rule marked unclear gives tests flagged "rule not confirmed"; a test that could trigger an action on a described tool is flagged.
28. Normal requests are always included, so a bot that refuses everything fails some.
29. The generated tests are saved against the setup version, all marked selected.

Check: ruff, mypy strict, pytest.

## Phase 5: Selecting, running and judging (seam 4)

30. Nothing runs before confirmation: starting a run with no confirmed selection is refused; a confirmation with no test ticked is refused.
31. Only the selected tests run (unticked ones are not sent to the endpoint and are not in the results).
32. A run sends at most 40 requests to the endpoint; the cap stops the run and the rest are saved as errors with the reason.
33. The judge (M5, interface unchanged) reads each reply with an app context built from the setup version's judge context and the test's own "what a correct reply looks like"; there is no plain-rules check, so the result is the judge's verdict alone: pass, fail, or inconclusive when the judge is unavailable, never a green pass.
34. An endpoint error, timeout or bad reply is an error result with the cause; the judge is not called for it.
35. The key is sent with the run request, held in memory for the run only and dropped at the end; a backend restart mid-run leaves the scan interrupted; the key appears in no saved row.
36. Each setup is a project, so its scans appear in History and can be compared; the scan records the setup version, the selected test ids and the endpoint host (never the key).
37. Compare between two scans of different setup versions lists which rules changed; scans of the demo bots and scans from before M6 are unchanged.
38. One scan at a time still holds across demo and real-bot scans.

Check: ruff, mypy strict, pytest; the production-image check in CI.

## Phase 6: The setup page (seam 5)

A route in the existing app behind the owner password. Slices, each a rendered-page test first:

39. Unlock with the password (held in memory only), then the setup page opens with the chat and the side panel.
40. The secure fields for URL, format and key are separate from the chat; the key is not part of any chat request (checked on the captured calls); Test connection shows the status and the raw reply.
41. The side panel lists fields with status, source tags and "edited by you"; clicking a field edits it; an edit shows as locked.
42. Required items are shown as required, and "Review the rules" stays locked until they are met.
43. The interviewer's follow-up questions show a Skip button; a skipped item shows as unclear.
44. File upload accepts only allowed types and sizes and shows plain refusals.
45. The rules screen shows typed rules, highlights unclear ones with the question that would clear them, and lets the user edit, delete, add and confirm.
46. The select page shows every test in full (prompt, what we are trying to find out, correct reply, risk, severity), all ticked; "rule not confirmed" and "could trigger a real action" flags; unticking works; confirm needs at least one ticked.
47. Run progress, with the same free-tier wait note as the demo scan page, and the dashboard opens on the finished scan.
48. Plain error messages for: wrong password, quota used up, endpoint unreachable, endpoint refused (address), bad reply format, budget reached.

Check: lint, typecheck, test, build, bundle check.

## Phase 7: Dashboard changes for real-bot scans (seam 5)

49. The Conversations tab says the tool log is not available for this kind of target; the "Plain rules" block says no plain rule applied and the judge's verdict stands alone.
50. The conclusion keeps the M4 wording, says the result is decided by an unvalidated AI judge from the reply alone, and never says safe, secure or ready.
51. The select page's flags and the rules at stake appear in the report; the report names the setup version and the rules that were in force.
52. Compare shows the changed rules between setup versions.
53. The results of demo-bot scans and old scans look exactly as before.

Check: lint, typecheck, test, build, bundle check.

## Phase 8: The call to action, docs and CI

54. The home page (design file) gets the "test your own AI chatbot" call to action leading to the setup page, and the copy in "How we test" is checked against what is now built.
55. `docs/M6-setup.md` in the shape of M5's: purpose, how it works with a diagram, the setup chat and the two contexts, the address checks, the key handling, the open items, testing, problems met, acceptance steps, limits, what M6 achieved.
56. README roadmap, tests table, config table (the new budget settings) and docs links; `docs/Frontend_Spec.md` updated for the new pages; `docs/Redflag_Milestones.md` rewritten for M6 and M8.
57. CI runs the new tests; the secret scanner stays on.

## Phase 9: Deploy (owner clicks, builder guides)

58. Push, confirm CI is green, confirm the backend deploy runs the new migration and the frontend deploy shows the setup page behind the lock.

## Phase 10: Live acceptance (owner)

Asked first, because it uses free quota and sends real traffic: point the flow at an HTTP endpoint the owner controls. Check: the chat and side panel, the secure key field, Test connection, required items, follow-up questions and Skip, the rules screen, the 30 described tests all ticked, unticking one and seeing it skipped, the dashboard on the finished scan with the real-bot wording, and a second setup version compared with the first. Only after the owner approves does the next milestone start.

## Risks to watch

- **The supervisor acting on hostile pasted text.** Deferred by the owner and listed as an open item; the basic fencing is tested in phase 3.
- **Aiming Redflag at a server the user does not own.** Permission is deferred; the address refusal, the request cap and the owner lock are tested in phases 1 and 5.
- **The key leaking.** Slices 2, 9, 15, 20 and 35 check every path: prompts, logs, rows, replies and responses.
- **Free-tier quota across five AI roles.** Separate budgets and clear errors; the judge degrades to inconclusive.
- **Judge-only verdicts looking firmer than they are.** The unvalidated wording is tested in phase 7.
- **Bad generated tests** (silly or duplicate prompts). Validation and the select page let the owner see and untick them; real quality is judged in acceptance.
- **Scope.** The plan is large. If a phase overruns, the owner is told before the next one starts.
