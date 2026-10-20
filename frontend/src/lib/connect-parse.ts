// "Paste anything you have": a link, a key, a code sample, JSON or a curl command. This reads what
// it can, in the browser, so a pasted key never leaves the page. What it reports back names what it
// found in words and never repeats a key.

export type ParsedConnection = {
  url?: string;
  key?: string;
  format?: "openai" | "custom";
  model?: string;
  headerName?: string;
  headerPrefix?: string;
  requestTemplate?: string;
  replyPath?: string;
  /** In words: "address", "key", "model", "format". Never a value. */
  found: string[];
  /** What is still needed, in words, such as "address" or "reply path". */
  missing: string[];
};

const MESSAGE_KEYS = ["message", "prompt", "question", "query", "input", "text"];
const KEY_HEADER = /key|token/i;

/** Undo the escaping a Windows "copy as cURL (cmd)" adds. */
function unescapeWindows(text: string): string {
  if (!/\^"/.test(text)) return text;
  return text
    .replace(/\^\r?\n/g, " ")
    .replace(/\^\\\^"/g, '\\"')
    .replace(/\^(.)/g, "$1");
}

/** Split a command line the way a shell would: spaces separate words, quotes group them. */
function shellSplit(text: string): string[] {
  const words: string[] = [];
  let current = "";
  let inWord = false;
  let quote: "'" | '"' | null = null;
  const source = text.replace(/\\\r?\n/g, " ");
  for (let i = 0; i < source.length; i += 1) {
    const c = source[i];
    if (quote === "'") {
      if (c === "'") quote = null;
      else current += c;
    } else if (quote === '"') {
      if (c === "\\" && (source[i + 1] === '"' || source[i + 1] === "\\")) {
        current += source[i + 1];
        i += 1;
      } else if (c === '"') quote = null;
      else current += c;
    } else if (c === "'" || c === '"') {
      quote = c;
      inWord = true;
    } else if (/\s/.test(c)) {
      if (inWord || current) words.push(current);
      current = "";
      inWord = false;
    } else {
      current += c;
      inWord = true;
    }
  }
  if (inWord || current) words.push(current);
  return words;
}

function fromCurl(words: string[], out: ParsedConnection): void {
  let body: string | undefined;
  for (let i = 0; i < words.length; i += 1) {
    const word = words[i];
    const next = words[i + 1];
    if ((word === "--url" || word === "-u") && next?.startsWith("http")) out.url = next;
    else if (/^https?:\/\//i.test(word) && !out.url) out.url = word;
    else if ((word === "-H" || word === "--header") && next) {
      const at = next.indexOf(":");
      if (at > 0) {
        const name = next.slice(0, at).trim();
        const value = next.slice(at + 1).trim();
        if (name.toLowerCase() === "authorization" && /^bearer\s+/i.test(value)) {
          out.key = value.replace(/^bearer\s+/i, "");
          out.headerName = name;
          out.headerPrefix = "Bearer ";
        } else if (KEY_HEADER.test(name) && value) {
          out.key = value;
          out.headerName = name;
          out.headerPrefix = "";
        }
      }
      i += 1;
    } else if (/^(-d|--data|--data-raw|--data-binary)$/.test(word) && next) {
      body = next;
      i += 1;
    }
  }
  if (body !== undefined) fromBody(body, out);
}

function fromBody(body: string, out: ParsedConnection): void {
  let data: unknown;
  try {
    data = JSON.parse(body);
  } catch {
    return;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return;
  const record = data as Record<string, unknown>;
  if (Array.isArray(record.messages)) {
    out.format = "openai";
    if (typeof record.model === "string") out.model = record.model;
    return;
  }
  out.format = "custom";
  const name = MESSAGE_KEYS.find((candidate) => typeof record[candidate] === "string");
  if (name) out.requestTemplate = JSON.stringify({ ...record, [name]: "{{prompt}}" });
}

function fromText(text: string, out: ParsedConnection): void {
  const link = /https?:\/\/[^\s"'<>)\],]+/i.exec(text);
  if (link) out.url = link[0];
  const bearer = /bearer\s+([A-Za-z0-9._~+/-]{8,})/i.exec(text);
  const named =
    /["']?(?:api[_-]?key|apikey|access[_-]?key|token)["']?\s*[=:]\s*["']([^"'\s]+)["']/i.exec(text) ??
    /\bapi[_-]?key\s*=\s*([^\s"',)]+)/i.exec(text);
  if (bearer) {
    out.key = bearer[1];
    out.headerName = "Authorization";
    out.headerPrefix = "Bearer ";
  } else if (named) {
    out.key = named[1];
  }
  const model = /\bmodel["']?\s*[=:]\s*["']([^"']+)["']/i.exec(text);
  if (model) out.model = model[1];
  if (
    (out.url && /\/chat\/completions\/?$/.test(out.url)) ||
    /chat\.completions|OpenAI\s*\(/.test(text) ||
    (/"messages"/.test(text) && /"role"/.test(text))
  ) {
    out.format = "openai";
  }
}

export function parseConnection(input: string): ParsedConnection {
  const out: ParsedConnection = { found: [], missing: [] };
  const text = unescapeWindows(input.trim());
  const words = shellSplit(text);
  if (words.includes("curl")) fromCurl(words, out);
  else fromText(text, out);
  if (!out.format && out.url && /\/chat\/completions\/?$/.test(out.url)) out.format = "openai";

  if (out.url) out.found.push("address");
  if (out.key) out.found.push("key");
  if (out.model) out.found.push("model");
  if (out.format) out.found.push("format");

  if (!out.url) out.missing.push("address");
  if (out.format === "custom" && !out.requestTemplate) out.missing.push("message field");
  if (out.format === "custom" && !out.replyPath) out.missing.push("reply path");
  return out;
}
