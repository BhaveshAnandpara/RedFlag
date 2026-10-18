import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthStatus } from "./health-status";

const API = "https://api.example.test";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("HealthStatus", () => {
  it("shows a healthy backend with database status, version and commit", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, {
          status: "ok",
          database: "ok",
          version: "1.2.3",
          commit: "abc1234",
          timestamp: "2026-10-18T12:00:00+00:00",
        }),
      ),
    );

    render(<HealthStatus apiUrl={API} />);

    expect(await screen.findByText("Backend is healthy")).toBeInTheDocument();
    expect(screen.getByText(/Database: ok/)).toBeInTheDocument();
    expect(screen.getByText(/Version 1\.2\.3/)).toBeInTheDocument();
    expect(screen.getByText(/Commit abc1234/)).toBeInTheDocument();
  });

  it("explains a degraded backend in plain language and never says healthy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(503, {
          status: "degraded",
          database: "error",
          version: "1.2.3",
          commit: null,
          timestamp: "2026-10-18T12:00:00+00:00",
        }),
      ),
    );

    render(<HealthStatus apiUrl={API} />);

    expect(
      await screen.findByText("Backend is running, but its database is not responding"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Backend is healthy")).not.toBeInTheDocument();
  });

  it("shows a waking-up message with elapsed seconds and retries until the backend answers", async () => {
    vi.useFakeTimers();
    const ok = { status: "ok", database: "ok", version: "1.2.3", commit: null, timestamp: "t" };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockResolvedValue(jsonResponse(200, ok)),
    );

    render(<HealthStatus apiUrl={API} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText(/Waking up the backend/)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText(/5 seconds/)).toBeInTheDocument();
    expect(screen.queryByText("Backend is healthy")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText("Backend is healthy")).toBeInTheDocument();
  });

  it("gives up with a plain-language error when the backend never answers", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    render(<HealthStatus apiUrl={API} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(95_000);
    });

    expect(screen.getByText("Could not reach the backend")).toBeInTheDocument();
    expect(screen.queryByText(/Waking up the backend/)).not.toBeInTheDocument();

    const callsWhenGivingUp = fetchMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(fetchMock.mock.calls.length).toBe(callsWhenGivingUp);
  });
});
