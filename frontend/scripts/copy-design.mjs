// Copies the design pages (design/explore) into public/design so the site serves them at
// /design/home.html, /design/scan.html and /design/results.html. The design folder stays the one
// place to edit them. It fails loudly if the source is missing, so a build never ships without them.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "..", "..", "design", "explore");
const target = resolve(here, "..", "public", "design");

if (!existsSync(source)) {
  console.error(`Could not find the design pages at ${source}.`);
  process.exit(1);
}

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
// The pages, their data and the shared flair script and styles (the pages 404 without flair.css).
// The screenshots folder (png) is never shipped.
const files = readdirSync(source).filter((name) => /\.(html|js|css)$/.test(name));
for (const name of files) cpSync(join(source, name), join(target, name));
console.log(`Copied ${files.length} design files to public/design.`);
