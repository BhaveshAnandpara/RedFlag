"use client";

import { useEffect, useState } from "react";

type Health = {
  status: string;
  database: string;
  version: string;
  commit: string | null;
  timestamp: string;
};

const RETRY_DELAY_MS = 3000;
// A cold start takes about a minute on the free host, so allow 90 seconds before giving up.
const MAX_WAIT_MS = 90_000;

export function HealthStatus({ apiUrl }: { apiUrl: string }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [gaveUp, setGaveUp] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();
    const clock = setInterval(
      () => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000)),
      1000,
    );

    async function attempt() {
      try {
        const response = await fetch(`${apiUrl}/health`);
        const body: Health = await response.json();
        if (!cancelled) setHealth(body);
        clearInterval(clock);
      } catch {
        // Network errors and non-JSON replies (a host's "starting up" page) mean
        // the backend is probably still waking up, so try again shortly.
        if (cancelled) return;
        if (Date.now() - startedAt >= MAX_WAIT_MS) {
          clearInterval(clock);
          setGaveUp(true);
        } else {
          retryTimer = setTimeout(attempt, RETRY_DELAY_MS);
        }
      }
    }
    attempt();

    return () => {
      cancelled = true;
      clearInterval(clock);
      clearTimeout(retryTimer);
    };
  }, [apiUrl]);

  if (!health && gaveUp) {
    return (
      <StatusCard tone="bad" label="Error">
        <h2 className="text-xl font-medium">Could not reach the backend</h2>
        <p>It did not answer after a minute and a half. Try reloading the page in a moment.</p>
      </StatusCard>
    );
  }

  if (!health) {
    return (
      <StatusCard tone="wait" label="Waiting">
        <h2 className="text-xl font-medium">Waking up the backend…</h2>
        <p>
          The free host sleeps when idle, so the first visit can take about a minute.{" "}
          {elapsedSeconds} seconds so far.
        </p>
      </StatusCard>
    );
  }

  if (health.status !== "ok") {
    return (
      <StatusCard tone="bad" label="Degraded">
        <h2 className="text-xl font-medium">
          Backend is running, but its database is not responding
        </h2>
        <p>The service is up, but it cannot reach its database right now.</p>
      </StatusCard>
    );
  }

  return (
    <StatusCard tone="good" label="Healthy">
      <h2 className="text-xl font-medium">Backend is healthy</h2>
      <p>Database: {health.database}</p>
      <p>Version {health.version}</p>
      {health.commit && <p>Commit {health.commit}</p>}
    </StatusCard>
  );
}

const TONES = {
  good: "border-emerald-700 bg-emerald-50 text-emerald-950 dark:border-emerald-400 dark:bg-emerald-950 dark:text-emerald-50",
  wait: "border-amber-700 bg-amber-50 text-amber-950 dark:border-amber-400 dark:bg-amber-950 dark:text-amber-50",
  bad: "border-red-700 bg-red-50 text-red-950 dark:border-red-400 dark:bg-red-950 dark:text-red-50",
} as const;

// The label is visible text, so status never relies on color alone.
function StatusCard({
  tone,
  label,
  children,
}: {
  tone: keyof typeof TONES;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section role="status" className={`space-y-2 rounded-lg border-2 p-6 ${TONES[tone]}`}>
      <p className="text-sm font-semibold tracking-wide uppercase">{label}</p>
      {children}
    </section>
  );
}
