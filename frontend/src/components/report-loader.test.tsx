import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeResult, makeScan } from "@/test-support/fixtures";

import { ReportLoader } from "./report-loader";

let routeId = "31";
let routeKey: string | null = "view-key";
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: routeId }),
  useSearchParams: () => new URLSearchParams(routeKey === null ? "" : `key=${routeKey}`),
}));

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const finished = () =>
  makeScan([makeResult({ test_id: "g-1", kind: "negative", risk: "LLM07", status: "fail", severity: "high", title: "Ask for the prompt" })], {
    id: 31,
    botId: "target-8",
    setup: { version: 1, rules: [] },
  });

beforeEach(() => {
  routeId = "31";
  routeKey = "view-key";
});
afterEach(() => vi.unstubAllGlobals());

describe("opening a report from its link", () => {
  it("reads the scan with the key in the link, sends no owner header, and shows the report", async () => {
    const fetchMock = vi.fn(async () => json(200, finished()));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReportLoader apiUrl="https://api.example.test" pollMs={5} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the report…");
    expect(await screen.findByRole("heading", { name: "Your bot · quick scan #31" })).toBeInTheDocument();
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
    expect(calls[0][0]).toBe("https://api.example.test/open-scans/31?key=view-key");
    expect(calls[0][1].headers as Record<string, string>).not.toHaveProperty("X-Owner-Token");
  });

  it("says the report was not found, without asking the backend, when the link has no key", () => {
    routeKey = null;
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<ReportLoader apiUrl="https://api.example.test" />);
    expect(screen.getByRole("alert")).toHaveTextContent("This report was not found, or the link is missing its key.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says the same for a link that is not about a scan number", () => {
    routeId = "abc";
    vi.stubGlobal("fetch", vi.fn());
    render(<ReportLoader apiUrl="https://api.example.test" />);
    expect(screen.getByRole("alert")).toHaveTextContent("This report was not found");
  });

  it("says the same for a wrong key, which the backend answers with 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(404, { detail: "no such scan" })));
    render(<ReportLoader apiUrl="https://api.example.test" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This report was not found, or the link is missing its key.");
  });

  it("says the backend may still be waking up when it cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("network"))));
    render(<ReportLoader apiUrl="https://api.example.test" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the backend. It may still be waking up.");
  });

  it("follows a scan that is still running until it finishes", async () => {
    const running = makeScan([], { id: 31, status: "running", botId: "target-8", setup: { version: 1, rules: [] } });
    const answers = [running, running, finished()];
    const fetchMock = vi.fn(async () => json(200, answers.length > 1 ? answers.shift() : answers[0]));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReportLoader apiUrl="https://api.example.test" pollMs={5} />);
    await waitFor(() => expect(screen.getByRole("heading", { name: /1 of 1 attacks got through/ })).toBeInTheDocument());
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3));
    const settled = fetchMock.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(fetchMock.mock.calls.length).toBe(settled); // it stops asking once the scan is finished
  });
});
