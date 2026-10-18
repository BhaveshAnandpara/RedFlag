# M1 build plan

Design: `docs/superpowers/specs/2026-10-19-m1-model-router-design.md`.
Method: test-first, one red-green slice at a time, at the two agreed seams (backend over HTTP with fake providers and a real Postgres; the test page as a rendered page with the network faked). Commit after each phase with every check green.

Design reminders that shape the order: the only faked boundary is the outside providers, so the app factory accepts injected providers. Real adapters come after the router logic is proven.

## Phase 1: Router core over HTTP (fake providers)

Settings and app wiring first, then one slice per behavior:

1. Settings: owner token, provider keys, paid switch and cap, cache and budget defaults. `create_app` accepts injected providers.
2. Owner lock: wrong or missing token returns 401 and no provider is called. `/health` stays public.
3. Happy path: first provider answers. Response carries answer, provider, model, `cached: false`, attempts, usage, paid flag, remaining budget.
4. Fallback on rate limit: first provider rate-limited, second answers, both attempts recorded.
5. Fallback on server error and on timeout (same behavior, parametrized).
6. No fallback on bad key or bad request: a typed error surfaces and no other provider is tried.
7. All providers fail: typed `all_providers_failed`, attempts listed, never reported as success.
8. Providers with no key are "not configured" and skipped.
9. Cooldown: after a rate limit the provider is skipped until its retry-after passes (fake clock).

Check: ruff, mypy strict, pytest all pass.

## Phase 2: Cache, budgets, test hooks, paid path (real Postgres)

10. Migration for the cache and attempt-log tables. Applies cleanly on local Postgres.
11. Cache hit: identical temperature-0 request is answered with `cached: true` and no provider call; the entry remembers which provider produced it.
12. Cache rules: temperature above 0 is not cached; expiry honored; hard size cap evicts oldest first (fake clock).
13. Budget caps: requests, tokens, wall time and concurrency each stop the session with a typed `budget_exceeded` naming the cap. Cached answers do not count as provider requests.
14. Test hooks: simulate a provider failure and clear the cache. Both require the owner token and reset on restart.
15. Paid path: off by default so paid models are never used; when on, results are labeled paid, estimated spend is tracked and the cap refuses further spend.
16. Secrets: keys never appear in responses, error bodies or log output on any failure path.
17. Provider status endpoint: configured or not, cooling down or not, no keys shown.

Check: all checks pass; migration applies on a fresh database; CORS updated for POST and the owner header.

## Phase 3: Real provider adapters

For each of Groq, Gemini and OpenRouter, verify the current API shape from the provider's own docs first (shapes and model names drift), then:

18. Adapter built on plain `httpx`; maps provider replies to the neutral answer.
19. Error classification: 429 to rate limited (with retry-after), 5xx to server error, timeouts, 401 and 403 to auth error, 400 to bad request, missing model to model unavailable. Empty or blocked replies are a typed error, never a successful empty answer.
20. Tested against sample provider responses, with no live calls in CI.

Check: adapters pass sample-response tests; one live smoke call per provider run by the builder with the owner's keys (not committed).

## Phase 4: Test page (frontend, test-first)

21. Locked state: no password, nothing can be sent.
22. Send a message and show the answer with provider, model and cache labels.
23. Show the switch log and the budget panel.
24. Simulate-failure and clear-cache buttons call the API.
25. Wrong password shows a plain error.

Check: lint, typecheck, Vitest, build and bundle check pass. The bundle check must still find no secrets, and the owner password must exist only in browser session storage, never in the build.

## Phase 5: Docs and CI

- `.env.example` entries (names only), README updated, `docs/M1-setup.md` written.
- CI runs the new tests. Nothing in CI calls a live provider.

## Phase 6: Deploy (owner clicks, builder guides)

1. Owner creates free keys: Groq console, Google AI Studio (Gemini), OpenRouter.
2. Builder generates a long random `OWNER_TOKEN`.
3. Owner adds the keys and token to Render's environment settings. The paid switch stays off.
4. Push; CI passes; Render redeploys and runs the new migration; Vercel redeploys the frontend.
5. Builder verifies the new endpoints reject a missing token on the live backend.

## Phase 7: Live acceptance (owner)

With real keys on the live site: ask one real question; ask it again and see it come from cache; simulate a quota failure and see the switch recorded; set a tiny budget and see a clean stop; try a wrong password and see it rejected. Do not start M2 until the owner approves.

## Risks to watch

- Free model names and limits change. Names live in configuration and are confirmed live.
- The Render restart clears cool-downs and budgets by design. Cache and log survive in Neon.
- Neon waking from idle can slow the first cache lookup. The database timeout already allows for it.
- Gemini can return a blocked or empty reply. It must surface as a typed error.
- Test-page password handling: it must not leak into logs, URLs or the bundle.
- Keep the Neon cache under its size cap so it cannot crowd out the 0.5 GB free plan.
