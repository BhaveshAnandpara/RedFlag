import { describe, expect, it } from "vitest";

import { many, makeResult, makeScan } from "@/test-support/fixtures";

import { buildReport } from "./report";
import { reportHtml } from "./report-html";

// A print-friendly page for the Markdown report (W5): open it, print it, save it as a PDF.

const MD = [
  "# Redflag scan report",
  "",
  "**Scan #7** · A bot · Status: completed",
  "",
  "## Conclusion",
  "",
  "1 of 2 attack tests failed.",
  "",
  "- first point",
  "- second point with **bold** and `code`",
  "",
  "| Test | Result |",
  "|---|---|",
  "| Read an order | FAIL |",
  "| Ask a thing \\| with a bar | PASS |",
  "",
  "### A failure",
  "",
  "- Evidence: it leaked",
  "  - Tester: hello",
  "  - Bot: world",
  "",
  "---",
  "",
  "This is not a guarantee of security.",
].join("\n");

describe("the printable report", () => {
  const html = reportHtml(MD, "Redflag scan #7");

  it("is a whole page with a title and a print stylesheet, and loads nothing from outside", () => {
    expect(html).toMatch(/^<!doctype html>/i);
    expect(html).toContain("<title>Redflag scan #7</title>");
    expect(html).toContain("@media print");
    expect(html).not.toMatch(/<script|<link|src=|@import|url\(/i);
  });

  it("turns headings, paragraphs, lists, tables, bold and code into plain HTML", () => {
    expect(html).toContain("<h1>Redflag scan report</h1>");
    expect(html).toContain("<h2>Conclusion</h2>");
    expect(html).toContain("<h3>A failure</h3>");
    expect(html).toContain("<p>1 of 2 attack tests failed.</p>");
    expect(html).toContain("<li>first point</li>");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<code>code</code>");
    expect(html).toContain("<hr>");
    expect(html).toContain("<th>Test</th>");
    expect(html).toContain("<td>FAIL</td>");
    expect(html).toContain("<td>Ask a thing | with a bar</td>");
  });

  it("nests a list inside the item it belongs to", () => {
    expect(html).toMatch(/<li>Evidence: it leaked\s*<ul>\s*<li>Tester: hello<\/li>\s*<li>Bot: world<\/li>\s*<\/ul>\s*<\/li>/);
  });

  it("escapes anything that looks like HTML, so a bot's reply cannot run in the print window", () => {
    const hostile = reportHtml("# T\n\n- Bot: <script>alert('x')</script> & <img src=x onerror=alert(1)>", "t");
    expect(hostile).not.toContain("<script>");
    expect(hostile).not.toContain("<img");
    expect(hostile).toContain("&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt; &amp; &lt;img src=x onerror=alert(1)&gt;");
    expect(reportHtml("# T", "<b>x</b>")).toContain("<title>&lt;b&gt;x&lt;/b&gt;</title>");
  });

  it("renders a real report end to end, and keeps its closing line", () => {
    const scan = makeScan([...many(2, "pass"), makeResult({ status: "fail", title: "A <b>bad</b> test" })]);
    const page = reportHtml(buildReport(scan), "Redflag scan #7");
    expect(page).toContain("<h1>Redflag scan report</h1>");
    expect(page).toContain("A &lt;b&gt;bad&lt;/b&gt; test");
    expect(page).toContain("This is not a guarantee of security. It only reports what these tests checked.");
    expect(page).not.toMatch(/\b(safe|secure|ready)\b/i);
  });
});
