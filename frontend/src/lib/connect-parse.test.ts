import { describe, expect, it } from "vitest";

import { parseConnection } from "./connect-parse";

// "Paste anything you have": a link, a key, a code sample or a curl command. The parser reads what
// it can, runs in the browser, and never lists a key in the words it reports back.

const KEY = ["sk", "live", "abcdef1234567890"].join("-");

describe("pasting a curl command", () => {
  const curl = `curl https://api.example.com/v1/chat/completions \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "my-model", "messages": [{"role": "user", "content": "hi"}]}'`;

  it("finds the address, the key, the header, the model and the OpenAI-compatible format", () => {
    const parsed = parseConnection(curl);
    expect(parsed.url).toBe("https://api.example.com/v1/chat/completions");
    expect(parsed.key).toBe(KEY);
    expect(parsed.headerName).toBe("Authorization");
    expect(parsed.headerPrefix).toBe("Bearer ");
    expect(parsed.format).toBe("openai");
    expect(parsed.model).toBe("my-model");
    expect(parsed.missing).toEqual([]);
  });

  it("reads a Windows copy of the same command", () => {
    const windows = `curl --url ^"https://api.example.com/v1/chat/completions^" ^
  -H ^"Authorization: Bearer ${KEY}^" ^
  --data-raw ^"^{^\\^"model^\\^":^\\^"my-model^\\^",^\\^"messages^\\^":^[^{^\\^"role^\\^":^\\^"user^\\^",^\\^"content^\\^":^\\^"hi^\\^"^}^]^}^"`;
    const parsed = parseConnection(windows);
    expect(parsed.url).toBe("https://api.example.com/v1/chat/completions");
    expect(parsed.key).toBe(KEY);
    expect(parsed.model).toBe("my-model");
  });

  it("turns a custom body into a template with the message slot, and asks for the reply path", () => {
    const custom = `curl -X POST https://bot.example.com/ask -H 'x-api-key: ${KEY}' --data '{"question":"hi","session":"abc"}'`;
    const parsed = parseConnection(custom);
    expect(parsed.format).toBe("custom");
    expect(parsed.requestTemplate).toBe('{"question":"{{prompt}}","session":"abc"}');
    expect(parsed.headerName).toBe("x-api-key");
    expect(parsed.headerPrefix).toBe("");
    expect(parsed.key).toBe(KEY);
    expect(parsed.missing).toEqual(["reply path"]);
  });

  it("finds the message under the usual names", () => {
    for (const name of ["message", "prompt", "question", "query", "input", "text"]) {
      const parsed = parseConnection(`curl https://x.example.com/c -d '{"${name}":"hello"}'`);
      expect(parsed.requestTemplate).toBe(`{"${name}":"{{prompt}}"}`);
    }
  });

  it("works with no key at all", () => {
    const parsed = parseConnection(`curl https://x.example.com/c -d '{"query":"hi"}'`);
    expect(parsed.key).toBeUndefined();
    expect(parsed.found).not.toContain("key");
  });
});

describe("pasting code, JSON or a plain link", () => {
  it("reads an OpenAI-style client call", () => {
    const code = `client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key="${KEY}")
resp = client.chat.completions.create(model="llama-3.3-70b", messages=[])`;
    const parsed = parseConnection(code);
    expect(parsed.url).toBe("https://api.groq.com/openai/v1");
    expect(parsed.key).toBe(KEY);
    expect(parsed.model).toBe("llama-3.3-70b");
    expect(parsed.format).toBe("openai");
  });

  it("reads a JSON snippet with an endpoint and a key", () => {
    const parsed = parseConnection(`{"endpoint": "https://bot.example.com/chat", "api_key": "${KEY}"}`);
    expect(parsed.url).toBe("https://bot.example.com/chat");
    expect(parsed.key).toBe(KEY);
  });

  it("reads a bare link, and a bare Bearer key", () => {
    expect(parseConnection("  https://bot.example.com/v1/chat/completions  ").url).toBe(
      "https://bot.example.com/v1/chat/completions",
    );
    expect(parseConnection(`Authorization: Bearer ${KEY}`).key).toBe(KEY);
  });

  it("does not take an ordinary word for a key", () => {
    expect(parseConnection("my key is hunter2 maybe").key).toBeUndefined();
  });

  it("finds nothing in text that is not about a bot, and says what is still needed", () => {
    const parsed = parseConnection("hello there, how are you?");
    expect(parsed.found).toEqual([]);
    expect(parsed.missing).toEqual(["address"]);
  });
});

describe("what it reports back", () => {
  it("names what it found in words and never repeats a key", () => {
    const parsed = parseConnection(`curl https://a.example.com/v1/chat/completions -H "Authorization: Bearer ${KEY}" -d '{"model":"m","messages":[]}'`);
    expect(parsed.found).toEqual(["address", "key", "model", "format"]);
    expect(JSON.stringify(parsed.found)).not.toContain(KEY);
    expect(parsed.missing.join(" ")).not.toContain(KEY);
  });
});
