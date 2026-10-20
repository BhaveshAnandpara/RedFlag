import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildReport } from "@/lib/report";
import type { ScanDetail } from "@/lib/scan";
import { many, makeResult, makeScan } from "@/test-support/fixtures";

import { Dashboard } from "./dashboard";

// OWASP risks with their MITRE ATLAS tags, and a printable report (W5).

const ATLAS = {
  source: "https://atlas.mitre.org/techniques",
  version: "ATLAS data 5.6.0",
  checked: "2026-10-20",
  note: "Redflag's own best match between each OWASP risk and MITRE ATLAS techniques. An empty list means no good match was found, not that the risk is covered.",
};

function withAtlas(scan: ScanDetail): ScanDetail {
  const tags: Record<string, { id: string; name: string }[]> = {
    LLM01: [
      { id: "AML.T0051", name: "LLM Prompt Injection" },
      { id: "AML.T0054", name: "LLM Jailbreak" },
    ],
    LLM02: [{ id: "AML.T0057", name: "LLM Data Leakage" }],
    LLM09: [],
  };
  return {
    ...scan,
    summary: {
      ...scan.summary,
      atlas: ATLAS,
      risks: scan.summary.risks.map((risk) => ({ ...risk, atlas: tags[risk.id] ?? [] })),
    },
  } as ScanDetail;
}

const SCAN = withAtlas(
  makeScan([makeResult({ risk: "LLM01", status: "fail" }), makeResult({ risk: "LLM02", status: "pass" }), ...many(1, "pass", { risk: "LLM09" })], { id: 7 }),
);

afterEach(() => vi.unstubAllGlobals());

function show(detail: ScanDetail = SCAN) {
  render(<Dashboard detail={detail} history={[]} onOpen={vi.fn()} loadScan={vi.fn(async () => detail)} />);
  return userEvent.setup();
}

describe("ATLAS tags on the risk bars", () => {
  it("shows each risk's ATLAS techniques in words, and says when none matched", () => {
    show();
    const list = screen.getByRole("list", { name: "Results by risk" });
    const risk = (name: string) => within(list).getByRole("listitem", { name });
    expect(risk("LLM01 Prompt Injection")).toHaveTextContent("ATLAS: AML.T0051 LLM Prompt Injection, AML.T0054 LLM Jailbreak");
    expect(risk("LLM02 Sensitive Information Disclosure")).toHaveTextContent("ATLAS: AML.T0057 LLM Data Leakage");
    expect(risk("LLM09 Misinformation")).toHaveTextContent("ATLAS: no close match");
  });

  it("says where the mapping came from and that it is a best match, not coverage", () => {
    show();
    const note = screen.getByRole("note", { name: "About the ATLAS tags" });
    expect(note).toHaveTextContent(/best match/i);
    expect(note).toHaveTextContent("ATLAS data 5.6.0");
    expect(note).toHaveTextContent("checked 2026-10-20");
    expect(note.querySelector("a")).toHaveAttribute("href", "https://atlas.mitre.org/techniques");
  });

  it("shows nothing about ATLAS for a scan saved before the tags existed", () => {
    show(makeScan(many(2, "pass"), { id: 3 }));
    expect(screen.queryByText(/ATLAS:/)).not.toBeInTheDocument();
    expect(screen.queryByRole("note", { name: "About the ATLAS tags" })).not.toBeInTheDocument();
  });
});

describe("the report with framework tags", () => {
  it("has a Framework tags section with every risk, its ATLAS techniques and where they came from", () => {
    const report = buildReport(SCAN);
    expect(report).toContain("## Framework tags");
    expect(report).toContain("- LLM01 Prompt Injection: AML.T0051 LLM Prompt Injection, AML.T0054 LLM Jailbreak");
    expect(report).toContain("- LLM09 Misinformation: no close ATLAS match");
    expect(report).toContain("ATLAS data 5.6.0");
    expect(report).toMatch(/best match/i);
    expect(report).not.toMatch(/\b(safe|secure|ready)\b/i);
  });

  it("leaves the section out of a report for an older scan", () => {
    expect(buildReport(makeScan(many(1, "pass")))).not.toContain("## Framework tags");
  });
});

describe("print or save as PDF", () => {
  function fakeWindow() {
    const calls: string[] = [];
    const win = {
      document: { write: (html: string) => calls.push(html), close: vi.fn() },
      focus: vi.fn(),
      print: vi.fn(),
    };
    return { win, calls };
  }

  it("opens the printable report in a new window and prints it", async () => {
    const { win, calls } = fakeWindow();
    vi.stubGlobal("open", vi.fn(() => win));
    const user = show();
    await user.click(screen.getByRole("button", { name: "Print or save as PDF" }));
    expect(window.open).toHaveBeenCalledWith("", "_blank");
    expect(calls[0]).toContain("<title>Redflag scan #7</title>");
    expect(calls[0]).toContain("<h1>Redflag scan report</h1>");
    expect(win.print).toHaveBeenCalled();
  });

  it("says plainly when the browser blocked the window, and still offers the download", async () => {
    vi.stubGlobal("open", vi.fn(() => null));
    const user = show();
    await user.click(screen.getByRole("button", { name: "Print or save as PDF" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/blocked the print window/i);
    expect(screen.getByRole("button", { name: "Download report" })).toBeInTheDocument();
  });
});
