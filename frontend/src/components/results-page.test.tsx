import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SavedScans } from "@/lib/samples";
import { many, makeResult, makeScan } from "@/test-support/fixtures";

import { ResultsPage } from "./results-page";

const WEAK = makeScan(
  [
    makeResult({ test_id: "a", title: "Read another customer's order", status: "fail", severity: "critical" }),
    makeResult({ test_id: "b", title: "Ask for the code", status: "fail", severity: "critical" }),
    ...many(2, "pass"),
  ],
  { id: 5, botId: "acme-weak" },
);
const HARDENED = makeScan(
  [
    makeResult({ test_id: "a", title: "Read another customer's order", status: "pass", severity: "critical" }),
    makeResult({ test_id: "b", title: "Ask for the code", status: "pass", severity: "critical" }),
    ...many(2, "pass"),
  ],
  { id: 6, botId: "acme-hardened" },
);
const SAMPLES: SavedScans = {
  format_version: 1,
  saved_at: "2026-10-20T12:00:00Z",
  scans: [HARDENED, WEAK], // deliberately not weak first
};

afterEach(() => vi.unstubAllGlobals());

describe("the public results page", () => {
  it("says honestly when nothing has been saved yet", () => {
    render(<ResultsPage samples={{ format_version: 1, saved_at: null, scans: [] }} />);
    expect(screen.getByText("No saved scans yet.")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("says these are saved real scans, not live ones, with the date and model on each", () => {
    render(<ResultsPage samples={SAMPLES} />);
    expect(screen.getByRole("heading", { level: 1, name: "Saved scan results" })).toBeInTheDocument();
    expect(screen.getByText(/saved real scans, not live ones/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Recorded on \d{4}-\d{2}-\d{2} with gemini-3\.5-flash-lite/),
    ).toBeInTheDocument();
  });

  it("opens on the weak bot's scan and has no way to start a scan or sign in", () => {
    render(<ResultsPage samples={SAMPLES} />);
    expect(screen.getByRole("heading", { name: "Scan #5" })).toBeInTheDocument(); // the weak scan
    expect(screen.queryByRole("button", { name: /run scan/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Scan results" })).toBeInTheDocument();
  });

  it("has Compare ready as weak versus hardened, with the same-model statement", async () => {
    const user = userEvent.setup();
    render(<ResultsPage samples={SAMPLES} />);
    await user.click(screen.getByRole("tab", { name: "Compare" }));
    expect(await screen.findByText(/The same model answered both scans/)).toBeInTheDocument();
    const changed = await screen.findByRole("list", { name: "Tests that changed" });
    expect(within(changed).getAllByRole("listitem")).toHaveLength(2);
    expect(within(changed).getByText(/Read another customer's order: FAIL to PASS/)).toBeInTheDocument();
  });

  it("lets a visitor switch to the hardened scan from History", async () => {
    const user = userEvent.setup();
    render(<ResultsPage samples={SAMPLES} />);
    await user.click(screen.getByRole("tab", { name: "History" }));
    const list = screen.getByRole("list", { name: "Scan history" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    await user.click(within(list).getByRole("button", { name: "Open scan #6" }));
    expect(screen.getByRole("heading", { name: "Scan #6" })).toBeInTheDocument(); // the hardened scan
  });

  it("makes no network request, whatever the visitor does", async () => {
    const fetchMock = vi.fn(() => {
      throw new Error("the public page must not call the network");
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ResultsPage samples={SAMPLES} />);
    for (const name of ["Tests", "Conversations", "Compare", "History", "Overview"]) {
      await user.click(screen.getByRole("tab", { name }));
    }
    await user.click(screen.getByRole("tab", { name: "Compare" }));
    await screen.findByText(/The same model answered both scans/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
