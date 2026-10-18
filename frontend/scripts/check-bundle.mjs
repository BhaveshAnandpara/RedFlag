// Fails if the built client bundle contains a database connection string with credentials.
// Run after `pnpm build`. Anything under .next/static is shipped to every visitor's browser.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const CLIENT_BUNDLE_DIR = ".next/static";
const CONNECTION_STRING = /postgres(?:ql)?(?:\+\w+)?:\/\/[^\s"'`/]+:[^\s"'`/]+@/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

let scanned = 0;
const leaks = [];
for (const file of walk(CLIENT_BUNDLE_DIR)) {
  if (!/\.(js|css|html|json|map|txt)$/.test(file)) continue;
  scanned += 1;
  if (CONNECTION_STRING.test(readFileSync(file, "utf8"))) leaks.push(file);
}

if (scanned === 0) {
  console.error(`No files found under ${CLIENT_BUNDLE_DIR}. Did you run the build first?`);
  process.exit(1);
}
if (leaks.length > 0) {
  console.error("Database connection string found in the client bundle:");
  for (const file of leaks) console.error(`  ${file}`);
  process.exit(1);
}
console.log(`Bundle check passed: ${scanned} client files scanned, no connection strings.`);
