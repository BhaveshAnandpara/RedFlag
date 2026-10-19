// Save two completed scans (one weak, one hardened) as the samples the public results page shows.
//
// Run from the frontend folder, after the two scans exist on the live backend:
//   pnpm export:samples --weak 5 --hardened 6
// It reads the owner password from the git-ignored .env.local at the repo root, asks the live API
// for the two scans, checks them against the rules in sample-rules.mjs, and only then writes
// src/data/sample-scans.json. Nothing is written if a rule is broken. It prints scan numbers and
// model names, never the password or any scan text.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { findProblems } from "./sample-rules.mjs";

const here = dirname(fileURLToPath(import.meta.url));

function option(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

const weakId = option("weak");
const hardenedId = option("hardened");
if (!weakId || !hardenedId) {
  fail("Usage: pnpm export:samples --weak <scan number> --hardened <scan number>");
}
const api = option("api", "https://redflag-8dcv.onrender.com").replace(/\/$/, "");
const envFile = resolve(option("env-file", resolve(here, "..", "..", ".env.local")));
const out = resolve(option("out", resolve(here, "..", "src", "data", "sample-scans.json")));

if (!existsSync(envFile)) fail(`Could not find ${envFile}.`);
const line = readFileSync(envFile, "utf8")
  .split(/\r?\n/)
  .find((l) => /^\s*OWNER_TOKEN\s*=/.test(l));
const token = line?.split("=").slice(1).join("=").trim().replace(/^["']|["']$/g, "");
if (!token) fail("OWNER_TOKEN is not set in the env file.");

async function fetchScan(id) {
  const response = await fetch(`${api}/scans/${id}`, { headers: { "X-Owner-Token": token } });
  if (!response.ok) fail(`The API answered ${response.status} for scan #${id}.`);
  return response.json();
}

const scans = [await fetchScan(weakId), await fetchScan(hardenedId)];
const samples = { format_version: 1, saved_at: new Date().toISOString(), scans };

const problems = findProblems(samples);
if (problems.length > 0) {
  console.error("Nothing was written, because:");
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}

writeFileSync(out, JSON.stringify(samples, null, 2) + "\n", "utf8");
for (const scan of scans) {
  console.log(
    `Saved scan #${scan.scan.id} (${scan.scan.bot_id}), answered by: ${scan.scan.models_used.join(", ") || "no model"}`,
  );
}
console.log(`Wrote ${out}`);
