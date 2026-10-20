#!/usr/bin/env node
// Run your Redflag tests from a build and fail the build on findings.
//
//   node ci/redflag-ci.mjs [--fail-on critical|high|medium|any] [--fail-on-unclear]
//                          [--version N] [--timeout SECONDS] [--poll SECONDS]
//
// Environment: REDFLAG_URL (the Redflag backend), REDFLAG_TOKEN (an API token for one setup, made
// on the setup page) and, if your bot needs one, REDFLAG_TARGET_KEY (the bot's own key).
//
// Exit codes: 0 the gate passed, 1 the gate failed, 2 something went wrong (bad settings, a
// refused token, a busy server, a run that could not be completed, or a timeout).
//
// A pass only means no test failed at or above the chosen level. It is not a guarantee of security.
// The token and the key are never printed.

const THRESHOLDS = ["critical", "high", "medium", "any"];

function parse(argv) {
  const options = { failOn: "critical", failOnUnclear: false, version: null, timeout: 900, poll: 5 };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const value = () => argv[++i];
    if (arg === "--fail-on") options.failOn = value();
    else if (arg === "--fail-on-unclear") options.failOnUnclear = true;
    else if (arg === "--version") options.version = Number(value());
    else if (arg === "--timeout") options.timeout = Number(value());
    else if (arg === "--poll") options.poll = Number(value());
    else throw new Error(`Unknown option ${arg}.`);
  }
  if (!THRESHOLDS.includes(options.failOn)) {
    throw new Error(`--fail-on must be one of: ${THRESHOLDS.join(", ")}.`);
  }
  for (const [name, value] of [["--timeout", options.timeout], ["--poll", options.poll]]) {
    if (!Number.isFinite(value) || value <= 0) throw new Error(`${name} must be a number above 0.`);
  }
  if (options.version !== null && !Number.isInteger(options.version)) {
    throw new Error("--version must be a whole number.");
  }
  return options;
}

export async function main(argv, env, fetchImpl, print, clock = {}) {
  const sleep = clock.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const now = clock.now ?? (() => Date.now());
  const secrets = [env.REDFLAG_TOKEN, env.REDFLAG_TARGET_KEY].filter(Boolean);
  // Whatever is printed first has any secret taken out of it.
  const say = (line) => print(secrets.reduce((text, secret) => text.split(secret).join("[removed]"), String(line)));

  let options;
  try {
    options = parse(argv);
  } catch (error) {
    say(error.message);
    return 2;
  }
  for (const name of ["REDFLAG_URL", "REDFLAG_TOKEN"]) {
    if (!env[name]) {
      say(`${name} is not set. See ci/redflag-ci.mjs for what the command needs.`);
      return 2;
    }
  }
  const base = env.REDFLAG_URL.replace(/\/+$/, "");
  const headers = { Authorization: `Bearer ${env.REDFLAG_TOKEN}`, "Content-Type": "application/json" };

  const body = {
    key: env.REDFLAG_TARGET_KEY || null,
    fail_on: options.failOn,
    fail_on_unclear: options.failOnUnclear,
    ...(options.version !== null ? { version: options.version } : {}),
  };
  let started;
  try {
    started = await fetchImpl(`${base}/ci/runs`, { method: "POST", headers, body: JSON.stringify(body) });
  } catch {
    say("Could not reach the Redflag server. It may still be waking up.");
    return 2;
  }
  if (started.status === 401) {
    say("The API token was not accepted. Make a new one on the setup page.");
    return 2;
  }
  if (started.status === 409) {
    const detail = await started.json().catch(() => ({}));
    say(
      detail?.error?.kind === "scan_running"
        ? "A scan is already running on that Redflag server. Try again in a few minutes."
        : "The run could not start: there are no tests to run for that setup.",
    );
    return 2;
  }
  if (!started.ok) {
    say(`Redflag answered with status ${started.status}, so the run did not start.`);
    return 2;
  }
  const { run_id: runId } = await started.json();
  say(`Started Redflag run #${runId}.`);

  const begun = now();
  for (;;) {
    let result;
    try {
      const response = await fetchImpl(`${base}/ci/runs/${runId}`, { method: "GET", headers });
      if (!response.ok) {
        say(`Redflag answered with status ${response.status} while waiting for the run.`);
        return 2;
      }
      result = await response.json();
    } catch {
      say("Lost the connection to the Redflag server while waiting for the run.");
      return 2;
    }
    if (result.status !== "running") return report(result, say);
    if (now() - begun >= options.timeout * 1000) {
      say(`The run did not finish within ${options.timeout} seconds.`);
      return 2;
    }
    await sleep(options.poll * 1000);
  }
}

function report(result, say) {
  const c = result.counts ?? {};
  say(`Results: ${c.pass ?? 0} passed, ${c.fail ?? 0} failed, ${(c.inconclusive ?? 0) + (c.error ?? 0)} unclear.`);
  for (const failure of result.failures ?? []) {
    say(`  FAIL ${failure.title} (${failure.severity ?? "not rated"}): ${failure.evidence}`);
  }
  for (const reason of result.gate?.reasons ?? []) say(`  - ${reason}`);
  say(result.gate?.message ?? "");
  const verdict = result.gate?.verdict;
  if (verdict === "pass") return 0;
  if (verdict === "fail") return 1;
  return 2;
}

const isCommand = process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop());
if (isCommand) {
  main(process.argv.slice(2), process.env, fetch, (line) => console.log(line)).then(
    (code) => process.exit(code),
    () => {
      console.log("The Redflag command stopped because of an unexpected problem.");
      process.exit(2);
    },
  );
}
