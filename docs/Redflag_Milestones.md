# Redflag: Milestone Plan

Redflag is an AI application security assessment platform. It tests whether LLM apps, RAG systems, agents and MCP tools obey their intended rules, and it shows evidence for every finding.

This plan breaks the Requirements Specification (FR-xx and NFR-xx IDs) into 11 milestones. Each milestone ends with a live deployment, which is checked before the next one starts.

## How we work

1. Build one milestone.
2. Test it, update the README, and deploy it.
3. Check the deployed site against the "done when" list.
4. Only then start the next milestone.

Every milestone includes its own automated tests and a short README update, so testing and documentation never pile up at the end.

## Overview

| # | Milestone | Live at the end |
|---|---|---|
| M0 | Foundation and first deploy | Frontend, backend and database deployed, with a health check |
| M1 | Model router | A chat page backed by provider fallback, caching and budgets |
| M2 | Demo targets and sandbox | Vulnerable and hardened demo bots with simulated tools |
| M3 | Scan engine (deterministic) | Run a scan and get evidence-based verdicts |
| M4 | Dashboard and reports | Findings, metrics, comparison and Markdown reports |
| M5 | Judge and evaluation quality | LLM judge with measured accuracy |
| M6 | Policy builder | Plain-language rules turned into generated tests |
| M7 | Adaptive and multi-turn attacks | Attack mutation and multi-turn escalation |
| M8 | External targets (HTTP and MCP) | Test your own endpoint or MCP server safely |
| M9 | Regression and CI | Saved suites and a scheduled pass/fail gate |
| M10 | Launch polish | Audit, privacy, accessibility, docs, demo video |

**Milestones that make it a product:** M0 to M4 give a working, deployed tool. M5 makes the results trustworthy. M6 to M9 are extensions, so you can stop after any of them with something finished.

---

## M0: Foundation and first deploy

**Goal:** Prove the whole free hosting path works before building features on top of it.

**What gets built**
- Repository, project structure, linting and a basic CI workflow
- Frontend, backend and database on free tiers (the exact stack is confirmed in this milestone)
- Environment-variable and secrets handling, with no keys in the repo
- A health-check endpoint, and a page that calls it

**Done when**
- A public URL loads the frontend, and the frontend shows a healthy response from the deployed backend
- The database connection works from the backend
- CI runs on every push
- No secret appears in the repo or the client bundle

**Spec items:** NFR-18, NFR-01

---

## M1: Model router

**Goal:** Reliable access to free-tier models, without a quota running out ending a scan.

**What gets built**
- A common provider interface with at least two providers
- Automatic fallback when a provider returns a rate-limit or server error, with the switch recorded
- Request caching, and per-scan limits on requests, tokens, time and concurrency
- A simple chat page to try it

**Done when**
- A simulated rate-limit makes the router switch providers instead of failing
- A repeated identical request is served from cache without a new API call
- A scan stops cleanly when its budget is reached

**Spec items:** FR-44, FR-45, FR-46, FR-47, NFR-05, NFR-10

---

## M2: Demo targets and sandbox

**Goal:** Safe applications to attack, and a standard way for Redflag to talk to any target.

**What gets built**
- A vulnerable support bot and a hardened version, selectable in the UI
- A fake secret, synthetic documents and a few simulated tools. A tool call is only written to a log, and no real email or API call ever happens
- A visible tool-call log
- A defined policy file format and a common target interface: send a message, get back a response plus the tool-call log
- Hardening defenses that can be switched on and off one at a time

**Done when**
- You can chat with both bots on the live site
- Every tool call appears in the log with its arguments
- Nothing in the sandbox can reach the network or any real system
- All data in the repo is synthetic

**Spec items:** FR-02, FR-07, NFR-02

---

## M3: Scan engine (deterministic)

**Goal:** Run attacks and decide pass or fail from observed behavior, not from what the bot says.

**What gets built**
- Project records and a versioned catalog of OWASP LLM risks with test mappings
- A first attack library: prompt injection, sensitive information disclosure, unsafe output handling, excessive agency
- Positive tests (normal requests should work) and negative tests (attacks should be blocked)
- RAG security tests with poisoned documents
- Deterministic verdicts: canary secrets, policy-violation checks and tool-log inspection
- Verdicts of pass, fail, inconclusive or error. Timeouts and provider errors are never counted as a pass
- Evidence saved for every test, with a run ID and the settings recorded

**Done when**
- A scan against the vulnerable bot produces failures, with evidence you can inspect
- The hardened bot produces fewer failures on the same suite
- A refusal in the text does not count as a pass if the tool log shows the action happened
- Errors are reported as errors

**Spec items:** FR-01, FR-13, FR-14, FR-16, FR-17, FR-18, FR-23, FR-25, FR-26, FR-28, FR-30, NFR-06

---

## M4: Dashboard and reports

**Goal:** Make the results understandable, so the product is usable by someone who has never seen it.

**What gets built**
- Scan configuration (categories, depth, budgets) and a live progress view
- Findings with expected behavior, observed behavior and evidence
- Attack success rate with sample sizes and uncertainty
- OWASP coverage showing tested, passed, failed and untested risks
- Scan history, and a vulnerable vs. hardened before/after comparison
- Remediation guidance linked to each finding
- Markdown report export

**Done when**
- A first-time visitor can run a demo scan and read the result without documentation
- The comparison view shows the effect of the hardened configuration
- The report clearly separates tested, untested and inconclusive risks

**Spec items:** FR-22, FR-24, FR-31, FR-32, FR-33, FR-34, FR-35, FR-36, FR-37, FR-38

---

## M5: Judge and evaluation quality

**Goal:** Make the semantic verdicts trustworthy, and show how much to trust them.

**What gets built**
- An LLM judge, used only where deterministic checks cannot decide
- A small labeling tool to hand-label results
- Judge validation: accuracy, false positives, false negatives, and the known limits
- A held-out attack set that is never used when tuning defenses

**Done when**
- The report shows judge agreement with your labels, with a stated sample size
- Categories where the judge is weak are listed as limitations
- The before/after result on the held-out set is reported alongside the main result

**Spec items:** FR-27, FR-29, NFR-07

---

## M6: Policy builder

**Goal:** Test an app against its own stated rules.

**What gets built**
- A form where you describe the AI's purpose, allowed actions, forbidden actions, data restrictions and tool permissions
- An LLM that converts the description into a structured, editable policy, with ambiguous rules highlighted
- An approval step before any tests are generated
- Test generation from the approved policy, with policy versions saved for comparison
- Guardrail tests that also check legitimate requests are not blocked

**Done when**
- You can describe an AI in plain language, approve the policy, and get a generated test set
- Two policy versions can be compared on their results
- No tests run on a policy the user has not approved

**Spec items:** FR-08, FR-09, FR-10, FR-11, FR-12, FR-15

---

## M7: Adaptive and multi-turn attacks

**Goal:** Go beyond a fixed attack list.

**What gets built**
- Mutation of failed and near-miss attacks into variants, within configured limits
- Multi-turn scenarios where an attack builds across several messages
- Attack lineage, and removal of near-duplicates so quota is not wasted

**Done when**
- A scan can produce variants over several generations and shows which attack came from which
- Multi-turn attacks run within the budget limits
- Adaptive findings are labeled separately from the fixed benchmark

**Spec items:** FR-20, FR-21

---

## M8: External targets (HTTP and MCP)

**Goal:** Test applications you own, beyond the built-in demo.

**What gets built**
- A connector for a configurable chat or API endpoint
- A connector for a supported MCP server that lists its tools and schemas
- Connection validation (reachability, protocol, authentication, basic function)
- Tests for tool permissions, unauthorized calls and parameter manipulation
- SSRF protection: loopback, private-network and cloud-metadata addresses are blocked
- Risky write operations limited to explicitly authorized, isolated environments

**Done when**
- A scan runs against an HTTP target and an MCP server you control
- Requests to blocked addresses are rejected
- The public demo still allows no unrestricted target URLs

**Spec items:** FR-03, FR-04, FR-05, FR-06, FR-19, NFR-03

---

## M9: Regression and CI

**Goal:** Catch security regressions automatically.

**What gets built**
- Saved test suites that can be rerun after a change
- Regression detection: vulnerabilities that return, and legitimate behavior that becomes blocked
- A CLI or API that CI can call, with a configurable pass/fail threshold
- A scheduled GitHub Actions scan

**Done when**
- A pipeline fails when results cross the configured threshold
- Provider outages mark a run as skipped, not failed
- A rerun after a fix shows what changed

**Spec items:** FR-39, FR-40, FR-41, FR-42, FR-43

---

## M10: Launch polish

**Goal:** Make the project ready to show.

**What gets built**
- Audit trail of configuration changes and scan actions
- Retention and deletion controls, and a clear statement of what is stored
- An accessibility pass (contrast, keyboard navigation, clear errors)
- A README with setup, a threat model, supported integrations and limitations
- A 2 to 3 minute demo video
- Resume bullets using real numbers from your own runs

**Done when**
- A stranger can understand, run and trust the demo from the README alone
- Every number in the resume bullets can be traced to a recorded run

**Spec items:** FR-48, NFR-04, NFR-14, NFR-16, NFR-17

---

## Ordering decisions to confirm

- **Policy builder (M6) comes after the judge (M5)**, because generated tests are only useful once verdicts are trustworthy. They can be swapped if you want the policy idea earlier.
- **External targets (M8) come late**, because they carry the most security risk. The built-in demo is fully safe first.
- **Free-tier limits and terms change.** Recheck every service's current limits at M0 and again before launch.
- **An OWASP checklist is not proof of security.** Every report must separate tested, untested and inconclusive risks.
