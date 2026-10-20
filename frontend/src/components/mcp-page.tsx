"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { ScanDetail } from "@/lib/scan";
import { describeError } from "@/lib/setup";
import { SetupApi } from "@/lib/setup-api";

import { Dashboard } from "./dashboard";
import { RunningView } from "./setup-page";

type Effect = "reads" | "acts";
type ToolInfo = {
  name: string;
  description: string;
  params: string[];
  effect_hint: "reads" | "unknown";
};
type Listing = { server: { name: string; version: string }; tools: ToolInfo[] };

const FIELD = "w-full rounded border-2 border-zinc-500 bg-white p-2 text-black";
const BUTTON = "rounded border-2 px-3 py-1 text-sm disabled:opacity-50";
const PRIMARY =
  "rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-black";

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <label className="block space-y-1">
      <span className="block text-sm font-medium">{label}</span>
      <input
        type={type}
        value={value}
        autoComplete="off"
        onChange={(event) => onChange(event.target.value)}
        className={FIELD}
      />
    </label>
  );
}

function refusal(status: number, body: { error?: { kind?: string } } | null): string {
  // A 401 means the backend has not opened this page yet.
  if (status === 401) return "This tool is not open yet. Please try again later.";
  switch (body?.error?.kind) {
    case "sandbox_required":
      return "A tool that changes things can only be called on a test or sandbox server. Tick the box to confirm that this is one.";
    case "unknown_tool":
      return "One of those tools is not on the server any more. Look at the tools again.";
    default:
      return describeError(status, body as never);
  }
}

export function McpPage({ apiUrl, pollMs = 2000 }: { apiUrl: string; pollMs?: number }) {
  // No password: the backend opens the MCP calls when it is set up to. A scan is read back with
  // the secret view key that starting it returned, kept only here in memory.
  const api = useMemo(() => new SetupApi(apiUrl, ""), [apiUrl]);
  const [problem, setProblem] = useState<string | null>(null);

  const [address, setAddress] = useState("");
  // The key lives only here, in memory: sent with the look and the run, never stored.
  const [key, setKey] = useState("");
  const [headerName, setHeaderName] = useState("Authorization");
  const [headerPrefix, setHeaderPrefix] = useState("Bearer ");
  const [listing, setListing] = useState<Listing | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [effects, setEffects] = useState<Record<string, Effect>>({});
  const [sandbox, setSandbox] = useState(false);

  const [scan, setScan] = useState<ScanDetail | null>(null);
  const viewKey = useRef("");
  const stopped = useRef(false);

  useEffect(() => {
    stopped.current = false;
    return () => {
      stopped.current = true;
    };
  }, []);

  const server = () => ({
    url: address.trim(),
    key: key || null,
    header_name: headerName.trim() || "Authorization",
    header_prefix: headerPrefix,
  });

  async function look() {
    setProblem(null);
    const result = await api.call<Listing>("POST", "/mcp-scans/check", server());
    if (!result.ok) {
      setProblem(refusal(result.status, result.data as never));
      return;
    }
    setListing(result.data);
    setTicked(new Set());
    setSandbox(false);
    // Only a tool the server itself calls read-only starts as "only reads".
    setEffects(
      Object.fromEntries(
        result.data.tools.map((t) => [t.name, t.effect_hint === "reads" ? "reads" : "acts"]),
      ),
    );
  }

  const exercise = (listing?.tools ?? [])
    .filter((t) => ticked.has(t.name))
    .map((t) => ({ name: t.name, effect: effects[t.name] ?? "acts" }));
  const needsSandbox = exercise.some((e) => e.effect === "acts");

  function toggle(name: string) {
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function fetchScan(scanId: number): Promise<ScanDetail> {
    const result = await api.call<ScanDetail>(
      "GET",
      `/open-scans/${scanId}?key=${encodeURIComponent(viewKey.current)}`,
    );
    if (!result.ok) throw new Error(`scan request failed with ${result.status}`);
    return result.data;
  }

  async function follow(scanId: number) {
    try {
      while (!stopped.current) {
        const body = await fetchScan(scanId);
        setScan(body);
        if (body.scan.status !== "running") return;
        await new Promise((resolve) => setTimeout(resolve, pollMs));
      }
    } catch {
      setProblem(describeError(0, null));
    }
  }

  async function run() {
    setProblem(null);
    const started = await api.call<{ scan_id: number; view_key: string }>("POST", "/mcp-scans", {
      ...server(),
      exercise,
      sandbox_confirmed: needsSandbox && sandbox,
    });
    if (!started.ok) {
      setProblem(refusal(started.status, started.data as never));
      return;
    }
    viewKey.current = started.data.view_key;
    await follow(started.data.scan_id);
  }

  return (
    <section className="space-y-6">
      <h1 className="text-3xl font-semibold">Check an MCP server</h1>

      {scan ? (
        <div className="space-y-4">
          {problem && <p role="alert">{problem}</p>}
          {scan.scan.status === "running" ? (
            <RunningView detail={scan} />
          ) : (
            <Dashboard
              detail={scan}
              history={[]}
              onOpen={() => undefined}
              loadScan={fetchScan}
            />
          )}
        </div>
      ) : (
        <div className="space-y-6">
          <p>
            Tool descriptions are always checked for hidden instructions, invisible characters and
            open-ended inputs. Tools are only called if you tick them. A clean result is not proof
            that a server is safe.
          </p>
          {problem && <p role="alert">{problem}</p>}

          <div className="space-y-2">
            <Field label="Server address" value={address} onChange={setAddress} />
            <Field label="Access key" value={key} onChange={setKey} type="password" />
            <details>
              <summary className="cursor-pointer text-sm">How the key is sent</summary>
              <div className="space-y-2 pt-2">
                <Field label="Key header name" value={headerName} onChange={setHeaderName} />
                <Field label="Key header prefix" value={headerPrefix} onChange={setHeaderPrefix} />
              </div>
            </details>
            <button type="button" onClick={look} disabled={!address.trim()} className={BUTTON}>
              Look at the tools
            </button>
          </div>

          {listing && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">
                {listing.tools.length} {listing.tools.length === 1 ? "tool" : "tools"}
                {listing.server.name ? ` on ${listing.server.name}` : ""}
              </h2>
              <p className="text-sm">
                Tick a tool to have Redflag call it with manipulated text. Say whether it only
                reads or changes things: a tool that changes things is only called on a test or
                sandbox server.
              </p>
              <ul aria-label="Tools on this server" className="space-y-2">
                {listing.tools.map((tool) => (
                  <li key={tool.name} className="space-y-1 rounded border-2 p-3">
                    <label className="flex items-center gap-2 font-medium">
                      <input
                        type="checkbox"
                        aria-label={`Call this tool: ${tool.name}`}
                        checked={ticked.has(tool.name)}
                        onChange={() => toggle(tool.name)}
                      />
                      {tool.name}
                    </label>
                    <p className="text-sm">{tool.description || "No description."}</p>
                    <label className="flex items-center gap-2 text-sm">
                      <span>What does {tool.name} do?</span>
                      <select
                        aria-label={`What does ${tool.name} do?`}
                        value={effects[tool.name] ?? "acts"}
                        onChange={(event) =>
                          setEffects({ ...effects, [tool.name]: event.target.value as Effect })
                        }
                        className="rounded border-2 border-zinc-500 bg-white p-1 text-black"
                      >
                        <option value="reads">Only reads</option>
                        <option value="acts">Changes things</option>
                      </select>
                    </label>
                  </li>
                ))}
              </ul>
              {needsSandbox && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={sandbox}
                    onChange={(event) => setSandbox(event.target.checked)}
                  />
                  This server is a test or sandbox, not production
                </label>
              )}
              <button
                type="button"
                onClick={run}
                disabled={needsSandbox && !sandbox}
                className={PRIMARY}
              >
                Run checks
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
