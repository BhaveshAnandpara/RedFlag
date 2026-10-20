import { describe, expect, it } from "vitest";

import { makeResult, makeScan } from "@/test-support/fixtures";

import {
  botModel,
  judgeModels,
  mcpFamily,
  mcpGroup,
  mcpKind,
  mcpModel,
  mcpTool,
  pct,
  seconds,
  when,
  wilson,
} from "./report-model";

describe("the range around a small count", () => {
  it("matches the range the dashboard showed for 2 of 26 attacks", () => {
    const [lo, hi] = wilson(2, 26);
    expect([pct(lo), pct(hi)]).toEqual(["2%", "24%"]);
  });

  it("has no range for nothing tested, and the full range at the ends", () => {
    expect(wilson(0, 0)).toEqual([0, 0]);
    expect(wilson(0, 10)[0]).toBe(0);
    expect(wilson(10, 10)[1]).toBe(1);
  });
});

describe("the times", () => {
  it("writes the start in UTC and the length in whole seconds", () => {
    expect(when(1_760_000_000)).toBe("2025-10-09 08:53 UTC");
    const scan = makeScan([]);
    expect(seconds(scan)).toBe(50);
  });
});

describe("a scan of the visitor's own bot", () => {
  const results = [
    makeResult({ test_id: "g-1", kind: "negative", risk: "LLM07", status: "fail", severity: "high" }),
    makeResult({ test_id: "g-2", kind: "negative", risk: "LLM02", status: "fail", severity: "critical" }),
    makeResult({ test_id: "g-3", kind: "negative", risk: "LLM02", status: "pass", severity: "high" }),
    makeResult({ test_id: "g-4", kind: "positive", risk: null, status: "pass", severity: null }),
    makeResult({ test_id: "g-5", kind: "positive", risk: null, status: "fail", severity: null }),
  ];
  const model = botModel(makeScan(results));

  it("counts attacks and normal requests separately, and a normal request that failed is not an attack", () => {
    expect(model.attacks).toHaveLength(3);
    expect(model.normal).toHaveLength(2);
    expect(model.failed.map((r) => r.test_id)).toEqual(["g-2", "g-1"]);
    expect(model.normalOk).toBe(1);
  });

  it("puts the worst failure first and counts the critical ones", () => {
    expect(model.failed[0].severity).toBe("critical");
    expect(model.critical).toBe(1);
  });

  it("works out the rate and the risks nothing tested", () => {
    expect(model.rate).toBeCloseTo(2 / 3);
    expect(model.untested).toBe(8);
    expect(model.tested).toEqual(["LLM02", "LLM07"]);
  });

  it("gives one coverage row per OWASP risk, with how many tests and how many failed", () => {
    expect(model.cover).toHaveLength(10);
    expect(model.cover.find((c) => c.id === "LLM02")).toMatchObject({ n: 2, f: 1 });
    expect(model.cover.find((c) => c.id === "LLM07")).toMatchObject({ n: 1, f: 1 });
    expect(model.cover.find((c) => c.id === "LLM03")).toMatchObject({ n: 0, f: 0 });
  });

  it("lists the judge models that answered, once each", () => {
    const judged = [
      makeResult({ judge_model: "llama-3.3-70b" }),
      makeResult({ judge_model: "llama-3.3-70b" }),
      makeResult({ judge_model: null }),
    ];
    expect(judgeModels(judged)).toEqual(["llama-3.3-70b"]);
  });
});

describe("reading an MCP result's id", () => {
  it("tells a description check from a call", () => {
    expect(mcpGroup("mcp-static-hidden_instructions")).toBe("static");
    expect(mcpGroup("mcp-dyn-read_file-traversal-path-1")).toBe("call");
  });

  it("finds the check family and the tool of a description check, including a tool name with hyphens", () => {
    expect(mcpFamily("mcp-static-hidden_instructions")).toBe("hidden_instructions");
    expect(mcpTool("mcp-static-hidden_instructions")).toBeNull();
    expect(mcpFamily("mcp-static-broad_parameters-my-tool")).toBe("broad_parameters");
    expect(mcpTool("mcp-static-broad_parameters-my-tool")).toBe("my-tool");
    expect(mcpFamily("mcp-static-not_a_family-x")).toBeNull();
  });

  it("finds the tool and the kind of a call, including a tool name with hyphens", () => {
    expect(mcpTool("mcp-dyn-read_file-traversal-path-1")).toBe("read_file");
    expect(mcpKind("mcp-dyn-read_file-traversal-path-1")).toBe("traversal");
    expect(mcpTool("mcp-dyn-my-tool-injection-sql-3")).toBe("my-tool");
    expect(mcpKind("mcp-dyn-run_query-prompt_injection-sql-8")).toBe("prompt_injection");
    expect(mcpTool("mcp-dyn-add-none")).toBe("add");
    expect(mcpKind("mcp-dyn-add-none")).toBeNull();
  });
});

describe("a check of an MCP server", () => {
  function scan() {
    const results = [
      makeResult({ test_id: "mcp-static-hidden_instructions-export_csv", status: "fail", severity: "critical" }),
      makeResult({ test_id: "mcp-static-hidden_characters", status: "pass", severity: "critical" }),
      makeResult({ test_id: "mcp-static-broad_parameters-read_file", status: "fail", severity: "medium" }),
      makeResult({ test_id: "mcp-dyn-read_file-traversal-path-1", status: "fail", severity: "critical" }),
      makeResult({ test_id: "mcp-dyn-read_file-oversized-path-5", status: "inconclusive", severity: "medium" }),
      makeResult({ test_id: "mcp-dyn-read_file-injection-path-3", status: "pass", severity: "high" }),
      makeResult({ test_id: "mcp-dyn-add-none", status: "not_applicable", severity: "medium" }),
    ];
    const built = makeScan(results);
    built.scan.settings.mcp = {
      target_host: "mcp.example",
      server: { name: "files", version: "2" },
      tool_count: 4,
      tools: ["read_file", "write_file", "export_csv", "add"],
      exercised: [
        { name: "read_file", effect: "reads" },
        { name: "write_file", effect: "acts" },
      ],
      sandbox_confirmed: true,
    };
    return built;
  }

  it("counts only passed and failed as decided, and puts the worst failure first", () => {
    const m = mcpModel(scan());
    expect(m.decided).toHaveLength(5);
    expect(m.failed.map((r) => r.test_id)).toEqual([
      "mcp-static-hidden_instructions-export_csv",
      "mcp-dyn-read_file-traversal-path-1",
      "mcp-static-broad_parameters-read_file",
    ]);
    expect(m.critical).toBe(2);
    expect(m.unclear).toBe(1);
  });

  it("counts calls apart from description checks, leaving out a tool with nothing to call", () => {
    const m = mcpModel(scan());
    expect(m.calls).toHaveLength(3);
    expect(m.callFails).toBe(1);
  });

  it("counts flagged tool descriptions but not tools that only have an open parameter", () => {
    const m = mcpModel(scan());
    expect([...m.flaggedTools]).toEqual(["export_csv"]);
  });

  it("says which tools were called, which only read, and which change things", () => {
    const m = mcpModel(scan());
    expect(m.called.map((c) => c.name)).toEqual(["read_file", "write_file"]);
    expect(m.changes.map((c) => c.name)).toEqual(["write_file"]);
    expect(m.readOnly).toEqual(["export_csv", "add"]);
  });

  it("gives a coverage row for each description check over every tool and each kind of call", () => {
    const m = mcpModel(scan());
    expect(m.cover).toHaveLength(8);
    expect(m.cover.find((c) => c.name === "Descriptions: hidden instructions")).toMatchObject({ n: 4, f: 1 });
    expect(m.cover.find((c) => c.name === "Inputs: open-ended parameters")).toMatchObject({ n: 4, f: 1 });
    expect(m.cover.find((c) => c.name === "Calls: path traversal")).toMatchObject({ n: 1, f: 1 });
    expect(m.cover.find((c) => c.name === "Calls: injection strings")).toMatchObject({ n: 1, f: 0 });
  });

  it("copes with a check saved before the tool names were kept", () => {
    const old = scan();
    delete old.scan.settings.mcp!.tools;
    const m = mcpModel(old);
    expect(m.toolNames).toEqual(["read_file", "write_file"]);
    expect(m.toolCount).toBe(4);
    expect(m.readOnly).toEqual([]);
  });
});
