"use client";

import type { JudgeAccuracy, Labeling, ScanDetail, ScanListItem } from "@/lib/scan";
import type { SetupApi } from "@/lib/setup-api";

import { CiPanel } from "./ci-panel";
import { Dashboard } from "./dashboard";

const FIELD = "w-full rounded border-2 border-zinc-500 bg-white p-2 text-black";
const PRIMARY =
  "rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-black";

/** Saving labels and reading the accuracy through the owner-only API. */
export function labelingFor(api: SetupApi, scanId: number): Labeling {
  return {
    async setLabel(testId, correct) {
      const path = `/scans/${scanId}/results/${encodeURIComponent(testId)}/label`;
      const result =
        correct === null
          ? await api.call("DELETE", path)
          : await api.call("PUT", path, { correct });
      if (!result.ok) throw new Error(`label request failed with ${result.status}`);
    },
    async loadAccuracy() {
      const result = await api.call<JudgeAccuracy>("GET", "/judge-accuracy");
      if (!result.ok) throw new Error(`accuracy request failed with ${result.status}`);
      return result.data;
    },
  };
}

/** A finished scan of a saved setup: run it again, run it from a build, and read the results. */
export function FinishedScan({
  api,
  scan,
  history,
  previous,
  keyValue,
  setKey,
  onRunAgain,
  onOpen,
  loadScan,
  setProblem,
}: {
  api: SetupApi;
  scan: ScanDetail;
  history: ScanListItem[];
  previous: ScanDetail | null;
  keyValue: string;
  setKey: (value: string) => void;
  onRunAgain: (scanId: number) => void;
  onOpen: (scanId: number) => void;
  loadScan: (scanId: number) => Promise<ScanDetail>;
  setProblem: (value: string | null) => void;
}) {
  const setup = scan.scan.settings.setup;
  const labeling = labelingFor(api, scan.scan.id);
  return (
    <div className="space-y-4">
      {setup && (
        <section
          aria-label="Run these tests again"
          role="region"
          className="space-y-2 rounded border-2 p-3 text-sm"
        >
          <h3 className="font-semibold">Run these tests again</h3>
          <p>
            Same setup version, same tests. Use it after you change your bot, to see what changed.
          </p>
          <label className="block space-y-1">
            <span className="block font-medium">API key for the run</span>
            <input
              type="password"
              autoComplete="off"
              value={keyValue}
              onChange={(event) => setKey(event.target.value)}
              className={FIELD}
            />
          </label>
          <button type="button" onClick={() => onRunAgain(scan.scan.id)} className={PRIMARY}>
            Run again
          </button>
        </section>
      )}
      {setup && <CiPanel api={api} setupId={setup.setup_id} setProblem={setProblem} />}
      <Dashboard
        detail={scan}
        history={history}
        onOpen={onOpen}
        loadScan={loadScan}
        previous={previous}
        labeling={labeling}
      />
    </div>
  );
}
