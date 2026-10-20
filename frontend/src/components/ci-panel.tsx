"use client";

import { useEffect, useState } from "react";

import { describeError } from "@/lib/setup";
import type { SetupApi } from "@/lib/setup-api";

type Token = {
  id: number;
  label: string;
  created_at: number;
  last_used_at: number | null;
  revoked: boolean;
};

const WORKFLOW = `- uses: BhaveshAnandpara/RedFlag/.github/actions/redflag-scan@main
  with:
    url: \${{ secrets.REDFLAG_URL }}
    token: \${{ secrets.REDFLAG_TOKEN }}
    target-key: \${{ secrets.REDFLAG_TARGET_KEY }}
    fail-on: high`;

const day = (epochSeconds: number) => new Date(epochSeconds * 1000).toISOString().slice(0, 10);

/**
 * Run the same tests from a build. A token belongs to this setup only, is shown once, and can only
 * start runs of this setup and read their results.
 */
export function CiPanel({
  api,
  setupId,
  setProblem,
}: {
  api: SetupApi;
  setupId: number;
  setProblem: (value: string | null) => void;
}) {
  const [tokens, setTokens] = useState<Token[]>([]);
  const [label, setLabel] = useState("github");
  const [shown, setShown] = useState<string | null>(null);

  async function load() {
    const result = await api.call<{ tokens: Token[] }>("GET", `/setups/${setupId}/ci-tokens`);
    if (result.ok) setTokens(result.data.tokens);
  }

  useEffect(() => {
    let cancelled = false;
    api.call<{ tokens: Token[] }>("GET", `/setups/${setupId}/ci-tokens`).then((result) => {
      if (!cancelled && result.ok) setTokens(result.data.tokens);
    });
    return () => {
      cancelled = true;
    };
  }, [api, setupId]);

  async function create() {
    setProblem(null);
    const result = await api.call<{ token: string }>("POST", `/setups/${setupId}/ci-tokens`, {
      label: label.trim() || "ci",
    });
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    setShown(result.data.token);
    await load();
  }

  async function revoke(token: Token) {
    setProblem(null);
    const result = await api.call("DELETE", `/setups/${setupId}/ci-tokens/${token.id}`);
    if (!result.ok) setProblem(describeError(result.status, result.data as never));
    await load();
  }

  return (
    <section
      aria-label="Use this in your builds"
      role="region"
      className="space-y-3 rounded border-2 p-3 text-sm"
    >
      <h3 className="font-semibold">Use this in your builds</h3>
      <p>
        Run these tests from GitHub Actions or any build, and fail the build when a test fails at or
        above a level you choose. A token belongs to this setup only: it can start runs of this
        setup and read their results, and nothing else.
      </p>
      <label className="block space-y-1">
        <span className="block font-medium">Token name</span>
        <input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          className="w-full rounded border-2 border-zinc-500 bg-white p-2 text-black"
        />
      </label>
      <button type="button" onClick={create} className="rounded border-2 px-3 py-1 text-sm">
        Create an API token
      </button>
      {shown && (
        <p role="status" className="break-all rounded border-2 p-2 font-mono text-xs">
          This token is shown only once. Copy it now and keep it in a secret, not in your code:{" "}
          <span className="font-semibold">{shown}</span>
        </p>
      )}
      {tokens.length > 0 && (
        <ul aria-label="Your API tokens" className="space-y-1">
          {tokens.map((token) => (
            <li key={token.id} className="flex flex-wrap items-baseline gap-2">
              <span>
                {token.label} · made {day(token.created_at)} ·{" "}
                {token.last_used_at ? `last used ${day(token.last_used_at)}` : "never used"}
                {token.revoked ? " · revoked" : ""}
              </span>
              {!token.revoked && (
                <button
                  type="button"
                  aria-label={`Revoke token ${token.label}`}
                  onClick={() => void revoke(token)}
                  className="rounded border-2 px-2 py-0.5 text-xs"
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="space-y-1">
        <p className="font-medium">In a GitHub workflow</p>
        <pre className="overflow-x-auto rounded border-2 p-2 text-xs">{WORKFLOW}</pre>
        <p>
          Or run it yourself with <code>node ci/redflag-ci.mjs --fail-on high</code>. It reads the
          three secrets as environment variables and exits 0 for a pass, 1 for a failed gate and 2
          if the run could not be completed.
        </p>
        <p className="text-xs">
          A pass only means no test failed at or above that level. This is not a guarantee of
          security. It only reports what these tests checked.
        </p>
      </div>
    </section>
  );
}
