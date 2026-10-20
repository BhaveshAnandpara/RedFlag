// Builds the stylesheet for the real Quick scan, MCP check and report pages from the CSS in the
// design prototypes (design/explore), so the design folder stays the one place the look is edited.
//
// Each prototype's rules are prefixed with one scope class (.d-quick, .d-mcp, .d-report) so the
// three pages, which reuse names like .btn and .badge with different sizes, never collide. What
// the three share (colours, resets, the header) is written once below. No dependency: the CSS in
// the prototypes is plain, so a small brace-matching reader is enough.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "..", "..", "design", "explore");
const target = resolve(here, "..", "src", "app", "(design)", "design.css");

const PAGES = [
  { file: "quick.html", scope: ".d-quick", extra: ["flair.css"] },
  { file: "mcp.html", scope: ".d-mcp", extra: ["flair.css"] },
  { file: "results.html", scope: ".d-report", extra: [] },
];

// Rules the shell writes once, not per page.
const GLOBAL = /^(:root|\*|html|body|button|input|select|textarea|a|header|nav|\[hidden\]|\.brand|\.proto)(?![\w-])/;

function styleOf(html) {
  return [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join("\n");
}

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

// Reads { prelude, body } blocks at the top level of a stretch of CSS.
function blocks(css) {
  const out = [];
  let depth = 0;
  let quote = null;
  let start = 0;
  let open = -1;
  for (let i = 0; i < css.length; i += 1) {
    const c = css[i];
    if (quote) {
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === "{") {
      if (depth === 0) open = i;
      depth += 1;
    } else if (c === "}") {
      depth -= 1;
      if (depth === 0) {
        out.push({ prelude: css.slice(start, open).trim(), body: css.slice(open + 1, i) });
        start = i + 1;
      }
    }
  }
  return out;
}

function splitSelectors(prelude) {
  const parts = [];
  let depth = 0;
  let quote = null;
  let current = "";
  for (const c of prelude) {
    if (quote) {
      if (c === quote) quote = null;
      current += c;
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    if (c === "(" || c === "[") depth += 1;
    if (c === ")" || c === "]") depth -= 1;
    if (c === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else current += c;
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}

const scoped = (scope, selector) => (selector.startsWith("main") && !/^main[\w-]/.test(selector) ? scope + selector.slice(4) : `${scope} ${selector}`);

function rules(css, scope, keyframes, globalMedia) {
  let out = "";
  for (const { prelude, body } of blocks(stripComments(css))) {
    if (prelude.startsWith("@keyframes")) {
      const name = prelude.split(/\s+/)[1];
      if (!keyframes.has(name)) keyframes.set(name, `${prelude} {${body}}\n`);
      continue;
    }
    if (prelude.startsWith("@media")) {
      const inner = rules(body, scope, keyframes, globalMedia);
      // header and nav rules inside a media query belong to the shell, kept once
      const shell = blocks(body)
        .filter((b) => splitSelectors(b.prelude).every((s) => GLOBAL.test(s)))
        .map((b) => `${b.prelude} {${b.body}}`)
        .join("\n");
      if (shell && !globalMedia.has(prelude)) globalMedia.set(prelude, shell);
      if (inner.trim()) out += `${prelude} {\n${inner}}\n`;
      continue;
    }
    const selectors = splitSelectors(prelude);
    if (selectors.every((s) => GLOBAL.test(s))) continue;
    out += `${selectors.map((s) => scoped(scope, s)).join(", ")} {${body}}\n`;
  }
  return out;
}

const SHELL = `
.rfd {
  --bg: #050505; --ink: #f4f4f2; --muted: #a3a3a3; --faint: #6f6f6f; --line: rgba(255,255,255,0.08);
  --red: #ff3b3f; --red-ink: #ff5a5f; --pass: #3fc07a; --amber: #f2b33d; --panel: #0b0b0b;
  --sans: var(--font-space-grotesk), "Space Grotesk", system-ui, sans-serif;
  --mono: var(--font-jetbrains-mono), "JetBrains Mono", ui-monospace, monospace;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
  min-height: 100vh; background: var(--bg); color: var(--ink); font-family: var(--sans);
  -webkit-font-smoothing: antialiased; color-scheme: dark;
}
.rfd *, .rfd *::before, .rfd *::after { box-sizing: border-box; }
.rfd [hidden] { display: none !important; } /* a layout rule must never un-hide an element */
.rfd button, .rfd input, .rfd select, .rfd textarea { font: inherit; color: inherit; }
.rfd button { background: none; border: 0; cursor: pointer; padding: 0; }
.rfd a { color: inherit; }
.rfd header { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 36px; height: 64px; padding: 0 24px; border-bottom: 1px solid var(--line); background: rgba(5,5,5,0.88); backdrop-filter: blur(8px); }
.rfd .brand { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 18px; letter-spacing: -0.02em; text-decoration: none; }
.rfd .brand svg { width: 15px; height: 17px; }
.rfd nav { display: flex; gap: 28px; font-size: 14px; }
.rfd nav a { color: var(--muted); text-decoration: none; }
.rfd nav a[aria-current] { color: var(--ink); }
/* states the prototypes did not draw: an unclear flag, and unclear badges in the quick scan thread */
.rfd .mf.unclear i { background: #5a4a26; transform: scaleY(0.45); }
.rfd .badge.unclear { color: var(--amber); background: rgba(242,179,61,0.12); }
.rfd .badge.na { color: var(--muted); background: #1c1c1c; }
@media (max-width: 720px) { .rfd header { gap: 16px; padding: 0 16px; } .rfd nav { display: none; } }
`;

if (!existsSync(source)) {
  console.error(`Could not find the design pages at ${source}.`);
  process.exit(1);
}

const keyframes = new Map();
const globalMedia = new Map();
let body = "";
for (const page of PAGES) {
  const html = readFileSync(join(source, page.file), "utf8");
  const css = [styleOf(html), ...page.extra.map((f) => readFileSync(join(source, f), "utf8"))].join("\n");
  body += `\n/* ${page.file} */\n${rules(css, page.scope, keyframes, globalMedia)}`;
}

const header = "/* Generated by scripts/build-design-css.mjs from design/explore. Edit the design pages, not this file. */\n";
const media = [...globalMedia.entries()].filter(([p]) => !p.includes("720px")).map(([p, b]) => `${p} {\n${b.replace(/(^|\n)(?=[^\n])/g, "$1  ").replace(/(^|\n)\s*(header|nav)/g, "$1  .rfd $2")}\n}`);
mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, `${header}${SHELL}\n${[...keyframes.values()].join("")}${body}\n${media.join("\n")}\n`);
console.log(`Wrote ${target}`);
