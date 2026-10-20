import { describe, expect, it } from "vitest";

import { makeResult, makeScan } from "@/test-support/fixtures";

import { conclusion, isMcp, isRealBot } from "./analytics";

function mcpScan() {
  const scan = makeScan([makeResult({ status: "pass" })]);
  scan.scan.settings.mcp = {
    target_host: "mcp.example",
    server: { name: "files", version: "2" },
    tool_count: 3,
    exercised: [{ name: "read_file", effect: "reads" }],
    sandbox_confirmed: false,
  };
  return scan;
}

describe("an MCP server scan", () => {
  it("is recognised, and is not mistaken for a demo bot", () => {
    expect(isMcp(mcpScan())).toBe(true);
    expect(isMcp(makeScan([]))).toBe(false);
    expect(isRealBot(mcpScan())).toBe(true);
  });

  it("explains what decided the results without claiming plain rules did not run", () => {
    const lines = conclusion(mcpScan()).details.join(" ");
    expect(lines).toMatch(/MCP server/);
    expect(lines).toMatch(/only called the tools you ticked/i);
    expect(lines).not.toMatch(/No plain rules ran/);
  });
});
