"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { readOpenScan } from "@/lib/open-api";
import type { ScanDetail } from "@/lib/scan";
import { SetupApi } from "@/lib/setup-api";

import { ReportView } from "./report-view";

type State = { kind: "loading" } | { kind: "missing" } | { kind: "down" } | { kind: "ready"; detail: ScanDetail };

/**
 * Opens a report from its link. The link carries the scan's secret view key, so whoever has the
 * link can read the report and nobody else can. A scan that is still running is followed.
 */
export function ReportLoader({ apiUrl, pollMs = 3000 }: { apiUrl: string; pollMs?: number }) {
  const params = useParams<{ id: string }>();
  const key = useSearchParams().get("key") ?? "";
  const id = Number(params.id);
  const api = useMemo(() => new SetupApi(apiUrl, ""), [apiUrl]);
  const [state, setState] = useState<State>({ kind: "loading" });
  const invalid = !key || !Number.isInteger(id);

  useEffect(() => {
    if (invalid) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const detail = await readOpenScan(api, id, key);
        if (!alive) return;
        setState({ kind: "ready", detail });
        if (detail.scan.status === "running") timer = setTimeout(load, pollMs);
      } catch (error) {
        if (!alive) return;
        // a 404 is a wrong or missing key; anything else is the backend being away
        setState({ kind: /404/.test(String(error)) ? "missing" : "down" });
      }
    };
    void load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [api, id, key, pollMs, invalid]);

  if (invalid) return <Notice kind="missing" />;
  if (state.kind === "ready") return <ReportView detail={state.detail} />;
  return <Notice kind={state.kind} />;
}

function Notice({ kind }: { kind: "loading" | "missing" | "down" | "ready" }) {
  const text =
    kind === "loading"
      ? "Loading the report…"
      : kind === "missing"
        ? "This report was not found, or the link is missing its key."
        : "Could not reach the backend. It may still be waking up. Try again in a moment.";
  return (
    <main className="d-report">
      <p className="card nomatch" role={kind === "loading" ? "status" : "alert"}>
        {text}
      </p>
    </main>
  );
}
